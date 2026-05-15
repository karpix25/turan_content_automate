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

function readDuration(html) {
  const match = html.match(/<div\s+id="main"[\s\S]*?data-duration="([^"]+)"/);
  const duration = Number(match?.[1]);
  return Number.isFinite(duration) && duration > 0 ? duration : 9999;
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

function compactHook(value, fallback) {
  const clean = normalize(value || fallback).replace(/[.!?…]+$/g, "");
  if (!clean) return "ВАЖНЫЙ ПОВОРОТ";
  const words = clean.split(" ");
  return words.length > 8 ? words.slice(0, 8).join(" ") : clean;
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
    scene.title,
    scene.headline,
    titleLines[0],
    scene.opener,
    scene.keyword,
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
    scene.subtitle,
    scene.main,
    scene.insight,
    scene.sourceText,
    scene.visualIdea,
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
  ]);
}

function pickKicker(scene, index) {
  return compactTitle(scene.blockName || scene.mode || scene.keyword || `сцена ${index + 1}`, `сцена ${index + 1}`).toLowerCase();
}

function pickHookContent(scenes) {
  const first = scenes[0] || {};
  const hookTitle = compactHook(
    first.hookText || first.opener || first.title || first.keyword,
    first.title || "ВАЖНЫЙ ПОВОРОТ",
  ).toUpperCase();
  const hookPromise = normalize(
    first.hookPromise ||
      first.referenceEssence ||
      first.subtitle ||
      first.insight ||
      first.sourceText ||
      "Сейчас станет понятно, где ломается привычная логика",
  );
  const hookKicker = compactTitle(first.blockName || "хук", "хук").toLowerCase();
  return { hookTitle, hookPromise, hookKicker };
}

function pickCardContent(scenes, cardIndex, totalCards, usedTitles) {
  const sceneIndex = cardIndex;
  const scene = scenes[sceneIndex] || {};
  if (!scene || !Object.keys(scene).length) {
    throw new Error(`No scene for card index ${cardIndex}`);
  }
  const titles = uniq([...sceneTitleCandidates(scene, cardIndex), ...sceneDescCandidates(scene)]);
  const descs = sceneDescCandidates(scene);
  let rawTitle = titles[0];
  if (!rawTitle) throw new Error(`Scene ${sceneIndex} has no usable title`);
  if (usedTitles.has(normalize(rawTitle).toLowerCase())) {
    rawTitle = titles.find((candidate) => !usedTitles.has(normalize(candidate).toLowerCase()));
    if (!rawTitle) throw new Error(`Scene ${sceneIndex} repeats title and has no alternate title`);
  }
  let rawDesc = descs[0];
  if (!rawDesc) throw new Error(`Scene ${sceneIndex} has no usable subtitle/description`);
  if (normalize(rawDesc).toLowerCase() === normalize(rawTitle).toLowerCase()) {
    rawDesc = descs.find((candidate) => normalize(candidate).toLowerCase() !== normalize(rawTitle).toLowerCase());
  }
  if (!rawDesc || isGeneric(rawDesc)) {
    throw new Error(`Scene ${sceneIndex} has weak subtitle/description`);
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
  const anchorWords = Array.isArray(scene.anchorWords) ? scene.anchorWords.map(normalize).filter(Boolean).join("; ") : "";
  const visualElements = Array.isArray(scene.visualElements)
    ? scene.visualElements.map(normalize).filter(Boolean).join("; ")
    : "";
  const visualType = normalize(scene.visualType || "illustration").toLowerCase();
  const isRealisticTextObject = ["realistic_interface", "realistic_document", "realistic_screenshot"].includes(visualType);
  const textPolicy = isRealisticTextObject
    ? `This is a ${visualType} visual: readable text is allowed only as short, realistic UI/document labels that belong inside the object. Keep labels brief, legible, and topic-specific; do not put the main headline/subtitle into the image.`
    : `This is an illustration/metaphor visual: no readable text, no numbers, no percent signs, no captions, no labels, no logos, no emojis inside the generated image.`;
  return normalize(
    [
      `Visualize this card as a beautiful illustration-first editorial infographic on a light background.`,
      `Visual type: ${visualType}.`,
      `Title: ${title}.`,
      `Subtitle: ${desc}.`,
      scene.referenceEssence ? `Reference essence to preserve in our own words: ${normalize(scene.referenceEssence)}.` : "",
      anchorWords ? `Speech anchor words: ${anchorWords}.` : "",
      scene.visualIdea ? `Core visual idea: ${normalize(scene.visualIdea)}.` : "",
      steps ? `Process: ${steps}.` : "",
      facts ? `Facts: ${facts}.` : "",
      visualElements ? `Possible symbolic elements: ${visualElements}.` : "",
      `Use subject -> action -> obstacle -> result logic as one concrete visual metaphor that matches this exact topic.`,
      `Choose objects, people, places, products, documents, tools, screens, money, flags, or other real-world anchors only when they are clearly supported by the title/subtitle/facts.`,
      `Do not introduce unrelated geopolitics, straits, ships, ports, maps, oil barrels, military imagery, or country flags unless this exact scene mentions them.`,
      textPolicy,
    ].join(" "),
  );
}

function updateFirst(block, pattern, replacement) {
  return block.replace(pattern, replacement);
}

function setAttr(block, name, value) {
  const escaped = escapeHtml(value);
  const pattern = new RegExp(`\\s${name}="[^"]*"`, "i");
  if (pattern.test(block)) return block.replace(pattern, ` ${name}="${escaped}"`);
  return block.replace(/<section\b/i, `<section ${name}="${escaped}"`);
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
const duration = readDuration(html);
const usedTitles = new Set();
const hook = pickHookContent(scenes);

html = html
  .replace(/(<div id="hook-kicker" class="hook-kicker">)[\s\S]*?(<\/div>)/, `$1${escapeHtml(hook.hookKicker)}$2`)
  .replace(/(<div id="hook-title" class="hook-title">)[\s\S]*?(<\/div>)/, `$1${escapeHtml(hook.hookTitle)}$2`)
  .replace(/(<div id="hook-promise" class="hook-promise">)[\s\S]*?(<\/div>)/, `$1${escapeHtml(hook.hookPromise)}$2`);

sectionMatches.forEach((match, index) => {
  if (index >= scenes.length) {
    let disabledBlock = match[0];
    disabledBlock = setAttr(disabledBlock, "data-disabled-card", "true");
    disabledBlock = setAttr(disabledBlock, "data-start", String(duration + 999 + index * 0.01));
    disabledBlock = setAttr(disabledBlock, "data-duration", "0.001");
    disabledBlock = setAttr(disabledBlock, "data-track-index", String(100 + index));
    html = html.replace(match[0], disabledBlock);
    return;
  }

  const { scene, title, desc, kicker } = pickCardContent(scenes, index, sectionMatches.length, usedTitles);
  usedTitles.add(normalize(title).toLowerCase());
  const brief = visualBrief(scene, title, desc);

  let block = match[0];
  block = setAttr(block, "data-disabled-card", "false");
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
console.log(`[apply-scene-plan-to-cards] Updated ${Math.min(sectionMatches.length, scenes.length)} active card(s) from ${scenes.length} scene(s).`);
