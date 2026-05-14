import { mkdir, readFile, writeFile } from "node:fs/promises";

const outputPath = new URL("../assets/generated/prompts.json", import.meta.url);
const indexPath = new URL("../index.html", import.meta.url);

const STYLE = [
  "Premium editorial illustrative infographic for the lower visual block of a vertical HeyGen Reels card.",
  "Create one beautiful 16:9 horizontal illustration that sits under a separate title and subtitle; this image is not a full poster.",
  "The entire subject must fit inside the 16:9 frame with safe margins, no cropping, no cut-off objects, and a centered composition.",
  "White paper or very light editorial background, subtle depth, bold red accent #b43c34, deep navy #0f172a, restrained blue #1d4f8f.",
  "Use a single strong visual metaphor or scene: route, barrier, ship, chessboard, map, document, shield, bridge, globe, spotlight, or other symbolic objects.",
  "Prefer polished vector/3D hybrid illustration, clean editorial composition, clear foreground/midground/background, generous white space, premium news-magazine quality.",
  "Show the idea through objects and action, not through data visualization.",
  "No charts, no gauges, no percentage rings, no dashboards, no UI panels, no tables, no repeated icon grids, no dense diagrams.",
  "No readable text, no numbers, no percent signs, no captions, no labels, no logos, no emojis, no photorealistic people, no clutter, no dark background.",
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
    `Create an illustration-first visual explanation of this beat.`,
    `Kicker/context: "${kicker || "none"}".`,
    `Title: "${title}".`,
    `Subtitle meaning: "${desc || "none"}".`,
    "Visualize the central relationship and consequence using one main symbolic scene with objects, routes, barriers, documents, maps, or physical metaphors.",
    "Avoid graph-like output unless the story absolutely requires it, and never use gauges, rings, dashboards, or visible percentages.",
    "The generated image must not repeat the title or subtitle as text and must not include readable words or numbers.",
    quote,
  ].join(" ");
}

function roleDirection(role) {
  const directions = {
    hook: "Make it a dramatic symbolic opening image with a clear central conflict and cinematic editorial energy.",
    blockade: "Show a physical blocked route or maritime barrier metaphor, with the path still readable and no chart elements.",
    response: "Show a decisive action or route continuing through pressure, using opposing objects rather than numbers.",
    proof: "Show evidence through a concrete scene: a ship crossing, a route confirmed, a magnifier, document, or spotlight.",
    conclusion: "Show a broad geopolitical metaphor such as a globe, crossroads, balance of forces, or shifted chessboard.",
    "quote interpretation": "Translate words into action visually, such as a document becoming a route, bridge, or moving vessel.",
    analysis: "Use a clean visual metaphor that explains cause and effect with one central object scene.",
  };
  return directions[role] || directions.analysis;
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
  prompt: `${STYLE} Card headline context: "${beat.title}". Beat role: ${beat.role}. Role direction: ${roleDirection(beat.role)} Visual brief: ${beat.visualBrief}`,
}));

await mkdir(new URL("../assets/generated/", import.meta.url), { recursive: true });
await writeFile(outputPath, `${JSON.stringify(prompts, null, 2)}\n`);

console.log(`Wrote ${prompts.length} image prompts to assets/generated/prompts.json`);
