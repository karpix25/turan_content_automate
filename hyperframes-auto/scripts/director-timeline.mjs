import { readFile, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";

const indexPath = new URL("../index.html", import.meta.url);
const transcriptPath = new URL("../assets/input/transcript.deepgram.json", import.meta.url);
const scenePlanPath = new URL("../assets/input/scene-plan.generated.json", import.meta.url);

const DIRECTOR = {
  overlayCoverageTarget: Math.max(
    0,
    Math.min(1, Number(process.env.HYPERFRAMES_OVERLAY_COVERAGE_PERCENT || 50) / 100),
  ),
  slideHoldExtension: 0.75,
  maxSingleOverlayDuration: 4.5,
  minSingleOverlayDuration: 1.8,
  minCleanVideoGap: Math.max(0, Number(process.env.HYPERFRAMES_MIN_CLEAN_VIDEO_GAP_SECONDS || 3)),
  hookReservedSeconds: 2.55,
  introOffset: 0,
  outroSafeTail: 0.35,
};

function readDuration(html) {
  const match = html.match(/<div\s+id="main"[\s\S]*?data-duration="([^"]+)"/);
  const duration = Number(match?.[1]);
  if (!Number.isFinite(duration) || duration <= 0) {
    throw new Error("Could not read root data-duration from index.html");
  }
  return duration;
}

function getBeatSections(html) {
  return [...html.matchAll(/<section\b[^>]*id="(beat-\d+)"[\s\S]*?<\/section>/g)]
    .map((match) => ({
      id: match[1],
      block: match[0],
      disabled: /data-disabled-card="true"/.test(match[0]),
    }))
    .filter((section) => !section.disabled);
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function cleanWord(value) {
  return String(value || "").replace(/[^\p{L}\p{N}]+/gu, "").toLowerCase();
}

async function readWords() {
  if (!existsSync(transcriptPath)) return [];
  const parsed = JSON.parse(await readFile(transcriptPath, "utf8"));
  let rawWords = parsed;
  if (!Array.isArray(rawWords)) {
    const channels = parsed.results?.channels || [];
    const alternatives = channels[0]?.alternatives || [];
    rawWords = alternatives[0]?.words || [];
  }
  if (!Array.isArray(rawWords)) return [];
  return rawWords
    .map((word) => ({
      text: cleanWord(word.punctuated_word || word.text || word.word),
      start: Number(word.start),
      end: Number(word.end),
    }))
    .filter((word) => word.text && Number.isFinite(word.start) && Number.isFinite(word.end));
}

async function readScenePlanTimings() {
  if (!existsSync(scenePlanPath)) return [];
  const scenes = JSON.parse(await readFile(scenePlanPath, "utf8"));
  if (!Array.isArray(scenes)) return [];
  return scenes
    .map((scene) => ({
      start: Number(scene.start),
      end: Number(scene.end),
    }))
    .filter((scene) => Number.isFinite(scene.start) && Number.isFinite(scene.end) && scene.end > scene.start);
}

function pickTranscriptAnchors(words, beatCount, totalDuration) {
  if (!words.length) return [];

  const speechStart = words[0].start;
  const speechEnd = Math.min(Math.max(words[words.length - 1].end, speechStart + 1), totalDuration);
  const usableDuration = Math.max(1, speechEnd - speechStart);
  const step = usableDuration / beatCount;
  const anchors = [];

  for (let index = 0; index < beatCount; index += 1) {
    const target = speechStart + step * index;
    const nearest = words.reduce((best, word) => {
      if (word.start < target - 1.6 || word.start > target + 1.6) return best;
      if (!best) return word;
      return Math.abs(word.start - target) < Math.abs(best.start - target) ? word : best;
    }, null);
    anchors.push(nearest?.start ?? target);
  }

  return [...new Set(anchors.map((time) => Number(time.toFixed(3))))]
    .filter((time) => time >= 0 && time < totalDuration - 0.5)
    .sort((a, b) => a - b)
    .slice(0, beatCount);
}

function fallbackAnchors(beatCount, totalDuration) {
  if (beatCount <= 0) return [];
  const usableDuration = Math.max(1, totalDuration - DIRECTOR.outroSafeTail);
  const step = usableDuration / beatCount;
  return Array.from({ length: beatCount }, (_, index) => Math.max(0, index * step + (index === 0 ? 0 : step * 0.18)));
}

function getUsableDuration(totalDuration) {
  const usableStart = Math.max(0, DIRECTOR.introOffset);
  const usableEnd = Math.max(usableStart + 0.5, totalDuration - DIRECTOR.outroSafeTail);
  return Math.max(0.5, usableEnd - usableStart);
}

function getFeasibleBeatCount(totalDuration, requestedCount) {
  if (requestedCount <= 1) return requestedCount;

  const usableDuration = getUsableDuration(totalDuration);
  for (let count = requestedCount; count > 1; count -= 1) {
    const requiredSeconds =
      count * DIRECTOR.minSingleOverlayDuration + (count - 1) * DIRECTOR.minCleanVideoGap;
    if (requiredSeconds <= usableDuration) return count;
  }

  return 1;
}

function chooseEvenly(items, count) {
  if (count >= items.length) return items.map((item, index) => ({ item, index }));
  if (count <= 1) return [{ item: items[0], index: 0 }];

  const selected = [];
  const used = new Set();
  const lastIndex = items.length - 1;

  for (let step = 0; step < count; step += 1) {
    let index = Math.round((step * lastIndex) / (count - 1));
    while (used.has(index) && index < items.length - 1) index += 1;
    while (used.has(index) && index > 0) index -= 1;
    if (!used.has(index)) {
      used.add(index);
      selected.push({ item: items[index], index });
    }
  }

  for (let index = 0; selected.length < count && index < items.length; index += 1) {
    if (!used.has(index)) {
      used.add(index);
      selected.push({ item: items[index], index });
    }
  }

  return selected.sort((a, b) => a.index - b.index);
}

function setSectionDisabled(section, disabled) {
  if (/data-disabled-card="[^"]*"/.test(section.block)) {
    return section.block.replace(/data-disabled-card="[^"]*"/, `data-disabled-card="${disabled ? "true" : "false"}"`);
  }

  return section.block.replace(/<section\b/, `<section data-disabled-card="${disabled ? "true" : "false"}"`);
}

function normalizeStarts(rawAnchors, beatCount, clipDuration, totalDuration) {
  const starts = [];
  const fallback = fallbackAnchors(beatCount, totalDuration);

  for (let index = 0; index < beatCount; index += 1) {
    const raw = rawAnchors[index] ?? fallback[index];
    const minStart = index === 0 ? DIRECTOR.introOffset : starts[index - 1] + clipDuration + DIRECTOR.minCleanVideoGap;
    const maxStart = Math.max(0, totalDuration - clipDuration - DIRECTOR.outroSafeTail);
    starts.push(clamp(raw, minStart, maxStart));
  }

  for (let index = starts.length - 2; index >= 0; index -= 1) {
    const maxStart = starts[index + 1] - clipDuration - DIRECTOR.minCleanVideoGap;
    starts[index] = Math.min(starts[index], Math.max(0, maxStart));
  }

  return starts.map((time) => Math.max(0, Number(time.toFixed(3))));
}

function updateSectionTiming(section, start, duration) {
  let block = section.block.replace(/data-start="[^"]+"/, `data-start="${start.toFixed(3)}"`);
  block = block.replace(/data-duration="[^"]+"/, `data-duration="${duration.toFixed(3)}"`);
  return block;
}

const html = await readFile(indexPath, "utf8");
const totalDuration = readDuration(html);
const sections = getBeatSections(html);
if (!sections.length) {
  throw new Error("No beat sections found in index.html");
}

const requestedBeatCount = sections.length;
const activeBeatCount = getFeasibleBeatCount(totalDuration, requestedBeatCount);
const selectedSections = chooseEvenly(sections, activeBeatCount);
const selectedSectionIndexes = new Set(selectedSections.map(({ index }) => index));
const activeSections = selectedSections.map(({ item }) => item);
const usableDuration = getUsableDuration(totalDuration);
const maxOverlaySeconds = Math.max(
  0.5,
  usableDuration - Math.max(0, activeBeatCount - 1) * DIRECTOR.minCleanVideoGap,
);
const targetOverlaySeconds = Math.min(totalDuration * DIRECTOR.overlayCoverageTarget, maxOverlaySeconds);
const rawClipDuration = targetOverlaySeconds / activeBeatCount;
const maxClipDuration = Math.max(0.5, Math.min(DIRECTOR.maxSingleOverlayDuration, maxOverlaySeconds / activeBeatCount));
const minClipDuration = Math.min(DIRECTOR.minSingleOverlayDuration, maxClipDuration);
const clipDuration = clamp(
  rawClipDuration + DIRECTOR.slideHoldExtension,
  minClipDuration,
  maxClipDuration,
);
const words = await readWords();
const sceneTimings = await readScenePlanTimings();
const useSceneTimings = sceneTimings.length >= requestedBeatCount;
const anchors = useSceneTimings
  ? selectedSections.map(({ index }, selectedIndex) => {
      const sceneStart = sceneTimings[index]?.start;
      if (!Number.isFinite(sceneStart)) return undefined;
      return Math.max(sceneStart, selectedIndex === 0 ? DIRECTOR.hookReservedSeconds : 0);
    })
  : pickTranscriptAnchors(words, activeBeatCount, totalDuration);
const starts = normalizeStarts(anchors, activeBeatCount, clipDuration, totalDuration);

let nextHtml = html;
let overlaySeconds = 0;
sections.forEach((section, index) => {
  if (!selectedSectionIndexes.has(index)) {
    nextHtml = nextHtml.replace(section.block, setSectionDisabled(section, true));
  }
});
activeSections.forEach((section, index) => {
  overlaySeconds += clipDuration;
  nextHtml = nextHtml.replace(section.block, updateSectionTiming(section, starts[index], clipDuration));
});

await writeFile(indexPath, nextHtml);

console.log("[director-timeline] Updated beat timing:");
console.log(`  duration: ${totalDuration.toFixed(3)}s`);
console.log(`  beats requested: ${requestedBeatCount}`);
console.log(`  beats active: ${activeBeatCount}`);
console.log(`  beats disabled: ${requestedBeatCount - activeBeatCount}`);
console.log(`  clip duration: ${clipDuration.toFixed(3)}s`);
console.log(`  min clean gap: ${DIRECTOR.minCleanVideoGap.toFixed(3)}s`);
console.log(`  hold extension: ${DIRECTOR.slideHoldExtension.toFixed(3)}s`);
console.log(`  overlay coverage: ${(overlaySeconds / totalDuration).toFixed(3)}`);
console.log(`  scene-plan timings: ${useSceneTimings ? "yes" : "no"}`);
console.log(`  transcript anchors: ${words.length ? "yes" : "no"}`);
console.log(`  starts: ${starts.map((time) => time.toFixed(3)).join(", ")}`);
