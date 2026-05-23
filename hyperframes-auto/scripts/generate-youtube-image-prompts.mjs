import { mkdir, readFile, writeFile } from "node:fs/promises";

const scenePlanPath = new URL("../assets/input/scene-plan.generated.json", import.meta.url);
const outputPath = new URL("../assets/generated/prompts.json", import.meta.url);

const requireAllImages = !["0", "false", "no", "off"].includes(
  String(process.env.HYPERFRAMES_YOUTUBE_REQUIRE_ALL_IMAGES ?? "true").trim().toLowerCase(),
);
const maxImages = Math.max(0, Number(process.env.HYPERFRAMES_YOUTUBE_KIE_MAX_IMAGES || 12));

const STYLE = [
  "Premium editorial YouTube 16:9 visual insert for an expert talking-head video.",
  "Create one cinematic explanatory image that can sit beside the speaker in a horizontal YouTube layout.",
  "Use a clean light editorial background, strong foreground subject, subtle depth, bold red accent #b43c34, deep navy #0f172a, restrained blue #1d4f8f.",
  "The image must explain the beat through one concrete scene: people, hands, products, tools, screens, documents, money, offices, factories, public spaces, barriers, or other real-world objects explicitly supported by the beat.",
  "Prefer polished vector/3D hybrid editorial illustration or realistic interface/document style when requested by the beat.",
  "No readable headline text, no logos, no emojis, no clutter, no fake brand marks.",
  "Do not introduce ships, ports, straits, country flags, military objects, oil infrastructure, maps, or geopolitics unless this exact beat explicitly mentions them.",
  "Avoid dashboard gauges, percentage rings, and dense charts unless the beat is specifically about data.",
].join(" ");

function normalizeText(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function generatedImageId(index) {
  return `youtube-scene-${String(index + 1).padStart(2, "0")}`;
}

function sceneScore(scene, index) {
  const mode = normalizeText(scene.mode).toLowerCase();
  const blockName = normalizeText(scene.blockName).toLowerCase();
  const visualIdea = normalizeText(scene.visualIdea);
  let score = visualIdea.length ? 10 : 0;
  if (mode === "full") score += 4;
  if (/хук|hook|контекст|context|risk|риск|solution|решен|итог|summary|вывод/.test(blockName)) score += 3;
  if (index === 0) score += 5;
  const duration = Number(scene.end) - Number(scene.start);
  if (Number.isFinite(duration) && duration >= 6) score += 2;
  return score;
}

function selectScenes(scenes) {
  if (!requireAllImages && maxImages <= 0) return [];
  const ranked = scenes
    .map((scene, index) => ({ scene, index, score: sceneScore(scene, index) }))
    .filter(({ scene }) =>
      normalizeText(scene.visualIdea) ||
      normalizeText(scene.title) ||
      normalizeText(scene.chapterTitle) ||
      normalizeText(scene.opener) ||
      normalizeText(scene.keyword) ||
      normalizeText(scene.subtitle) ||
      normalizeText(scene.chapterSubtitle) ||
      normalizeText(scene.insight) ||
      (Array.isArray(scene.titleLines) && scene.titleLines.some(normalizeText))
    )
    .sort((a, b) => b.score - a.score || a.index - b.index);

  if (requireAllImages) {
    return ranked.sort((a, b) => a.index - b.index);
  }

  const selected = [];
  for (const item of ranked) {
    const start = Number(item.scene.start);
    const tooClose = selected.some((chosen) => Math.abs(Number(chosen.scene.start) - start) < 24);
    if (tooClose && selected.length >= Math.ceil(maxImages / 2)) continue;
    selected.push(item);
    if (selected.length >= maxImages) break;
  }
  return selected.sort((a, b) => a.index - b.index);
}

function visualTypeInstruction(scene) {
  const visualType = normalizeText(scene.visualType).toLowerCase();
  if (visualType === "realistic_interface") {
    return "Render this as a realistic interface or screen object, with only tiny non-readable UI marks unless short object labels are necessary.";
  }
  if (visualType === "realistic_document") {
    return "Render this as a realistic document/object scene with stamps, folders, desk details, and only short non-prominent labels if necessary.";
  }
  if (visualType === "realistic_screenshot") {
    return "Render this as a realistic screenshot-like product or dashboard scene only if the beat clearly supports it; keep text minimal.";
  }
  return "Render this as an editorial explanatory illustration, not a chart and not a poster.";
}

const scenes = JSON.parse(await readFile(scenePlanPath, "utf8"));
if (!Array.isArray(scenes) || !scenes.length) {
  throw new Error(`Scene plan must be a non-empty array: ${scenePlanPath.pathname}`);
}

const selected = selectScenes(scenes);
const prompts = selected.map(({ scene, index }) => {
  const id = generatedImageId(index);
  const title = normalizeText(scene.title || scene.chapterTitle || scene.opener);
  const subtitle = normalizeText(scene.subtitle || scene.chapterSubtitle || scene.insight);
  const visualIdea = normalizeText(scene.visualIdea);
  const visualElements = Array.isArray(scene.visualElements)
    ? scene.visualElements.map(normalizeText).filter(Boolean).slice(0, 6)
    : [];
  const sourceText = normalizeText(scene.sourceText);
  return {
    id,
    file: `${id}.png`,
    aspectRatio: "1:1",
    resolution: "1K",
    prompt: [
      STYLE,
      visualTypeInstruction(scene),
      `YouTube semantic block title: "${title}".`,
      `Meaning/subtitle: "${subtitle}".`,
      `Visual idea: ${visualIdea || "one concrete expert scene that explains the semantic block"}.`,
      visualElements.length ? `Required concrete elements: ${visualElements.join("; ")}.` : "",
      sourceText ? `Speech context: ${sourceText}.` : "",
      "The generated image must not duplicate the title/subtitle as large readable text.",
    ].filter(Boolean).join(" "),
  };
});

await mkdir(new URL("../assets/generated/", import.meta.url), { recursive: true });
await writeFile(outputPath, `${JSON.stringify(prompts, null, 2)}\n`);

console.log(`Wrote ${prompts.length} YouTube KIE prompt(s) to assets/generated/prompts.json`);
