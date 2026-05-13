import { readFile, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";

const indexPath = new URL("../index.html", import.meta.url);
const transcriptPath = new URL("../assets/input/transcript.deepgram.json", import.meta.url);

const DIRECTOR = {
  overlayCoverageTarget: 0.5,
  maxSingleOverlayDuration: 3.7,
  minSingleOverlayDuration: 1.8,
  minCleanVideoGap: 1.2,
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
  return [...html.matchAll(/<section\b[^>]*id="(beat-\d+)"[\s\S]*?<\/section>/g)].map((match) => ({
    id: match[1],
    block: match[0],
  }));
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
  if (!Array.isArray(parsed)) return [];
  return parsed
    .map((word) => ({
      text: cleanWord(word.text),
      start: Number(word.start),
      end: Number(word.end),
    }))
    .filter((word) => word.text && Number.isFinite(word.start) && Number.isFinite(word.end));
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
  const usableDuration = Math.max(1, totalDuration - DIRECTOR.outroSafeTail);
  const step = usableDuration / beatCount;
  return Array.from({ length: beatCount }, (_, index) => Math.max(0, index * step + (index === 0 ? 0 : step * 0.18)));
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

const targetOverlaySeconds = totalDuration * DIRECTOR.overlayCoverageTarget;
const rawClipDuration = targetOverlaySeconds / sections.length;
const clipDuration = clamp(
  rawClipDuration,
  DIRECTOR.minSingleOverlayDuration,
  DIRECTOR.maxSingleOverlayDuration,
);
const words = await readWords();
const anchors = pickTranscriptAnchors(words, sections.length, totalDuration);
const starts = normalizeStarts(anchors, sections.length, clipDuration, totalDuration);

let nextHtml = html;
sections.forEach((section, index) => {
  nextHtml = nextHtml.replace(section.block, updateSectionTiming(section, starts[index], clipDuration));
});

await writeFile(indexPath, nextHtml);

const overlaySeconds = clipDuration * sections.length;
console.log("[director-timeline] Updated beat timing:");
console.log(`  duration: ${totalDuration.toFixed(3)}s`);
console.log(`  beats: ${sections.length}`);
console.log(`  clip duration: ${clipDuration.toFixed(3)}s`);
console.log(`  overlay coverage: ${(overlaySeconds / totalDuration).toFixed(3)}`);
console.log(`  transcript anchors: ${words.length ? "yes" : "no"}`);
console.log(`  starts: ${starts.map((time) => time.toFixed(3)).join(", ")}`);
