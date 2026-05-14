import { readFile, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";

const indexPath = new URL("../index.html", import.meta.url);
const scenePlanPath = new URL("../assets/input/scene-plan.generated.json", import.meta.url);

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function normalize(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}

function isGeneric(value) {
  const text = normalize(value).toLowerCase();
  if (!text) return true;
  return (
    /^смысловой блок$/.test(text) ||
    /^ключевая мысль$/.test(text) ||
    /^ключевой смысл/.test(text) ||
    /^глубокая аналитическая мысль$/.test(text) ||
    /^шаг\s*\d+$/i.test(text) ||
    /^показатель\s*\d+$/i.test(text) ||
    /^метрика\s*\d+$/i.test(text) ||
    /^блок\s*\d+$/i.test(text)
  );
}

function compactTitle(value, fallback) {
  const clean = normalize(value || fallback).replace(/[.!?…]+$/g, "");
  if (!clean) return "СМЫСЛОВОЙ БЛОК";
  const words = clean.split(" ");
  return words.length > 5 ? words.slice(0, 5).join(" ") : clean;
}

function uniq(values) {
  const seen = new Set();
  return values
    .map(normalize)
    .filter(Boolean)
    .filter((value) => !isGeneric(value))
    .filter((value) => {
      const key = value.toLowerCase();
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
}

function sceneTitleCandidates(scene, index) {
  const titleLines = Array.isArray(scene.titleLines) ? scene.titleLines.map(normalize).filter(Boolean) : [];
  const facts = Array.isArray(scene.facts) ? scene.facts.map((fact) => normalize(fact?.text || fact)).filter(Boolean) : [];
  const steps = Array.isArray(scene.steps) ? scene.steps.map(normalize).filter(Boolean) : [];
  const bars = Array.isArray(scene.bars) ? scene.bars.map((bar) => normalize(bar?.label || bar)).filter(Boolean) : [];
  return uniq([
    scene.headline,
    scene.title,
    titleLines[0],
    scene.keyword,
    scene.opener,
    titleLines[1],
    facts[0],
    steps[0],
    facts[1],
    steps[1],
    scene.insight,
    bars[0],
    bars[1],
    bars[2],
    bars[3],
    scene.cta,
  ]);
}

function sceneDescCandidates(scene) {
  const titleLines = Array.isArray(scene.titleLines) ? scene.titleLines.map(normalize).filter(Boolean) : [];
  const facts = Array.isArray(scene.facts) ? scene.facts.map((fact) => normalize(fact?.text || fact)).filter(Boolean) : [];
  const steps = Array.isArray(scene.steps) ? scene.steps.map(normalize).filter(Boolean) : [];
  const bars = Array.isArray(scene.bars) ? scene.bars.map((bar) => normalize(bar?.label || bar)).filter(Boolean) : [];
  return uniq([
    scene.main,
    scene.insight,
    titleLines[1],
    scene.cta,
    scene.keyword,
    facts[0],
    steps[0],
    facts[1],
    steps[1],
    facts[2],
    steps[2],
    bars[0],
    bars[1],
    bars[2],
    bars[3],
    titleLines[0],
    scene.opener,
    "Ключевой смысл этого фрагмента.",
  ]);
}

function pickKicker(scene, index) {
  return compactTitle(scene.blockName || scene.mode || scene.keyword || `сцена ${index + 1}`, `сцена ${index + 1}`).toLowerCase();
}

const FALLBACK_TITLES = [
  "ГЛАВНЫЙ РИСК",
  "ЧТО МЕНЯЕТСЯ",
  "ПОЧЕМУ ЭТО ВАЖНО",
  "ЧТО ДЕЛАТЬ",
  "НОВАЯ РЕАЛЬНОСТЬ",
  "КЛЮЧЕВОЙ ВЫВОД",
  "ГДЕ ОШИБКА",
  "ЧТО ВИДИТ ЗРИТЕЛЬ",
];

function pickCardContent(scenes, cardIndex, totalCards, usedTitles) {
  const sceneIndex = Math.min(scenes.length - 1, Math.floor((cardIndex * scenes.length) / Math.max(1, totalCards)));
  const scene = scenes[sceneIndex] || {};
  const variantIndex = Math.max(0, cardIndex - Math.floor((sceneIndex * totalCards) / Math.max(1, scenes.length)));
  const titles = uniq([...sceneTitleCandidates(scene, cardIndex), ...sceneDescCandidates(scene), ...FALLBACK_TITLES]);
  const descs = sceneDescCandidates(scene);
  let rawTitle = titles[variantIndex % titles.length] || titles[0] || FALLBACK_TITLES[cardIndex % FALLBACK_TITLES.length];
  if (usedTitles.has(normalize(rawTitle).toLowerCase())) {
    rawTitle =
      titles.find((candidate) => !usedTitles.has(normalize(candidate).toLowerCase())) ||
      FALLBACK_TITLES.find((candidate) => !usedTitles.has(normalize(candidate).toLowerCase())) ||
      rawTitle;
  }
  let rawDesc = descs[variantIndex % descs.length] || descs[0] || "Ключевой смысл этого фрагмента.";
  if (normalize(rawDesc).toLowerCase() === normalize(rawTitle).toLowerCase()) {
    rawDesc = descs[(variantIndex + 1) % descs.length] || scene.insight || scene.cta || rawDesc;
  }
  if (isGeneric(rawDesc)) {
    rawDesc = descs.find((candidate) => !isGeneric(candidate) && normalize(candidate).toLowerCase() !== normalize(rawTitle).toLowerCase()) || "Ключевая мысль этого фрагмента.";
  }
  return {
    scene,
    title: compactTitle(rawTitle, `Блок ${cardIndex + 1}`).toUpperCase(),
    desc: normalize(rawDesc),
    kicker: pickKicker(scene, sceneIndex),
  };
}

function visualBrief(scene, title, desc) {
  const steps = Array.isArray(scene.steps) ? scene.steps.map(normalize).filter(Boolean).join(" -> ") : "";
  const facts = Array.isArray(scene.facts) ? scene.facts.map((fact) => normalize(fact?.text || fact)).filter(Boolean).join("; ") : "";
  const visualElements = Array.isArray(scene.visualElements)
    ? scene.visualElements.map(normalize).filter(Boolean).join("; ")
    : "";
  return normalize(
    [
      `Visualize this card as a beautiful illustration-first editorial infographic on a light background.`,
      `Title: ${title}.`,
      `Subtitle: ${desc}.`,
      steps ? `Process: ${steps}.` : "",
      facts ? `Facts: ${facts}.` : "",
      visualElements ? `Possible symbolic elements: ${visualElements}.` : "",
      `Use subject -> action -> obstacle -> result logic as one concrete visual metaphor that matches this exact topic.`,
      `Choose objects, people, places, products, documents, tools, screens, money, flags, or other real-world anchors only when they are clearly supported by the title/subtitle/facts.`,
      `Do not introduce unrelated geopolitics, straits, ships, ports, maps, oil barrels, military imagery, or country flags unless this exact scene mentions them.`,
      `Do not request charts, gauges, percentage rings, dashboards, tables, visible numbers, or readable text.`,
    ].join(" "),
  );
}

function updateFirst(block, pattern, replacement) {
  return block.replace(pattern, replacement);
}

if (!existsSync(scenePlanPath)) {
  console.log("[apply-scene-plan-to-cards] No scene plan found, keeping existing cards.");
  process.exit(0);
}

const scenes = JSON.parse(await readFile(scenePlanPath, "utf8"));
if (!Array.isArray(scenes) || !scenes.length) {
  console.log("[apply-scene-plan-to-cards] Scene plan is empty, keeping existing cards.");
  process.exit(0);
}

let html = await readFile(indexPath, "utf8");
const sectionMatches = [...html.matchAll(/<section\b[\s\S]*?<\/section>/gi)].filter((match) => /id="beat-\d+"/.test(match[0]));
const usedTitles = new Set();

sectionMatches.forEach((match, index) => {
  const { scene, title, desc, kicker } = pickCardContent(scenes, index, sectionMatches.length, usedTitles);
  usedTitles.add(normalize(title).toLowerCase());
  const brief = visualBrief(scene, title, desc);

  let block = match[0];
  if (block.includes("data-visual-brief=")) {
    block = block.replace(/data-visual-brief="[^"]*"/, `data-visual-brief="${escapeHtml(brief)}"`);
  } else {
    block = block.replace(/(<section\b)/, `$1 data-visual-brief="${escapeHtml(brief)}"`);
  }
  block = updateFirst(block, /<div class="kicker">[\s\S]*?<\/div>/, `<div class="kicker">${escapeHtml(kicker)}</div>`);
  block = updateFirst(block, /<h([12])[^>]*>[\s\S]*?<\/h\1>/, (_full, level) => `<h${level}>${escapeHtml(title)}</h${level}>`);
  block = updateFirst(block, /<div class="desc">[\s\S]*?<\/div>/, `<div class="desc">${escapeHtml(desc)}</div>`);
  html = html.replace(match[0], block);
});

await writeFile(indexPath, html);
console.log(`[apply-scene-plan-to-cards] Updated ${sectionMatches.length} cards from ${scenes.length} scene(s).`);
