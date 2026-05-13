import { mkdir, readFile, writeFile } from "node:fs/promises";

const outputPath = new URL("../assets/generated/prompts.json", import.meta.url);
const indexPath = new URL("../index.html", import.meta.url);

const STYLE = [
  "Premium editorial infographic for the lower visual block of a vertical HeyGen Reels card.",
  "The image must feel like a clean illustration placed under a separate title and subtitle, not a full poster.",
  "White paper background, subtle light gray grid, bold red accent #b43c34, deep navy #0f172a, restrained blue #1d4f8f.",
  "Use large readable symbols, premium vector/3D hybrid, strong hierarchy, generous white space, and a polished news-graphics look.",
  "Show relationships, action, obstacle, and result; make the scene immediately readable without relying on text.",
  "No tiny text, no long labels, no logos, no photorealistic people, no clutter, no dark background, no cinematic lighting.",
].join(" ");

function attr(block, name) {
  const match = block.match(new RegExp(`${name}="([^"]*)"`, "i"));
  return match?.[1] || "";
}

function text(block, selector) {
  const patterns = {
    kicker: /<div class="kicker">([\s\S]*?)<\/div>/i,
    title: /<h[12][^>]*>([\s\S]*?)<\/h[12]>/i,
    desc: /<div class="desc">([\s\S]*?)<\/div>/i,
    quoteSource: /<div class="quote-source">([\s\S]*?)<\/div>/i,
  };
  const raw = block.match(patterns[selector])?.[1] || "";
  return raw.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
}

function inferRole({ kicker, title, desc }) {
  const joined = `${kicker} ${title} ${desc}`.toLowerCase();
  if (/хук|hook/.test(joined)) return "hook";
  if (/цитат|перевод|quote|сделаешь/.test(joined)) return "quote interpretation";
  if (/итог|вывод|conclusion|расстановка/.test(joined)) return "conclusion";
  if (/проходит|проход|proof|проверка/.test(joined)) return "proof";
  if (/запрет|закрыт|блокад|ультиматум|ban|blockade/.test(joined)) return "blockade";
  if (/ответ|игнор|response/.test(joined)) return "response";
  return "analysis";
}

function fallbackVisualBrief({ title, desc, kicker, quoteSource }) {
  const quote = quoteSource ? ` Quote attribution/context: ${quoteSource}.` : "";
  return [
    `Create a clean visual explanation of this beat.`,
    `Kicker/context: "${kicker || "none"}".`,
    `Title: "${title}".`,
    `Subtitle meaning: "${desc || "none"}".`,
    "Visualize the central relationship and consequence using symbols, routes, barriers, arrows, gauges, documents, maps, or object metaphors as appropriate.",
    "The generated image must not repeat the title or subtitle as text.",
    quote,
  ].join(" ");
}

const html = await readFile(indexPath, "utf8");
const sectionMatches = [...html.matchAll(/<section\b[\s\S]*?<\/section>/gi)];
const BEATS = sectionMatches
  .map(([block]) => {
    const id = attr(block, "id");
    if (!id || !block.includes("beat-card")) return null;
    const kicker = text(block, "kicker");
    const title = text(block, "title");
    const desc = text(block, "desc");
    const quoteSource = text(block, "quoteSource");
    const visualBrief = attr(block, "data-visual-brief") || fallbackVisualBrief({ title, desc, kicker, quoteSource });
    return {
      id,
      title,
      role: inferRole({ kicker, title, desc }),
      visualBrief,
    };
  })
  .filter(Boolean);

if (!BEATS.length) {
  console.error("No beat sections found in index.html");
  process.exit(1);
}

const prompts = BEATS.map((beat) => ({
  id: beat.id,
  file: `${beat.id}.png`,
  aspectRatio: "16:9",
  resolution: "1K",
  prompt: `${STYLE} Card headline context: "${beat.title}". Beat role: ${beat.role}. Visual brief: ${beat.visualBrief}`,
}));

await mkdir(new URL("../assets/generated/", import.meta.url), { recursive: true });
await writeFile(outputPath, `${JSON.stringify(prompts, null, 2)}\n`);

console.log(`Wrote ${prompts.length} image prompts to assets/generated/prompts.json`);
