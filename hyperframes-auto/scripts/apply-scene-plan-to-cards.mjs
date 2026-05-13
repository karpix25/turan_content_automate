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

function compactTitle(value, fallback) {
  const clean = normalize(value || fallback).replace(/[.!?…]+$/g, "");
  if (!clean) return "СМЫСЛОВОЙ БЛОК";
  const words = clean.split(" ");
  return words.length > 5 ? words.slice(0, 5).join(" ") : clean;
}

function pickTitle(scene, index) {
  const titleLines = Array.isArray(scene.titleLines) ? scene.titleLines.map(normalize).filter(Boolean) : [];
  return compactTitle(
    scene.headline ||
      scene.title ||
      titleLines[0] ||
      scene.keyword ||
      scene.blockName,
    `Блок ${index + 1}`,
  ).toUpperCase();
}

function pickDesc(scene) {
  const titleLines = Array.isArray(scene.titleLines) ? scene.titleLines.map(normalize).filter(Boolean) : [];
  return normalize(
    scene.main ||
      scene.insight ||
      titleLines[1] ||
      scene.cta ||
      scene.keyword ||
      "Ключевой смысл этого фрагмента.",
  );
}

function pickKicker(scene, index) {
  return compactTitle(scene.blockName || scene.mode || scene.keyword || `сцена ${index + 1}`, `сцена ${index + 1}`).toLowerCase();
}

function visualBrief(scene, title, desc) {
  const steps = Array.isArray(scene.steps) ? scene.steps.map(normalize).filter(Boolean).join(" -> ") : "";
  const facts = Array.isArray(scene.facts) ? scene.facts.map((fact) => normalize(fact?.text || fact)).filter(Boolean).join("; ") : "";
  const bars = Array.isArray(scene.bars)
    ? scene.bars.map((bar) => `${normalize(bar?.label)} ${Math.round(Number(bar?.value || 0) * 100)}%`).join("; ")
    : "";
  return normalize(
    [
      `Visualize this card as a lower white-background infographic.`,
      `Title: ${title}.`,
      `Subtitle: ${desc}.`,
      steps ? `Process: ${steps}.` : "",
      facts ? `Facts: ${facts}.` : "",
      bars ? `Relative indicators: ${bars}.` : "",
      `Use subject -> action -> obstacle -> result logic.`,
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

sectionMatches.forEach((match, index) => {
  const scene = scenes[Math.min(index, scenes.length - 1)] || {};
  const title = pickTitle(scene, index);
  const desc = pickDesc(scene);
  const kicker = pickKicker(scene, index);
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
