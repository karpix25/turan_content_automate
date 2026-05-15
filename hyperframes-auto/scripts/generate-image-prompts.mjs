import { mkdir, readFile, writeFile } from "node:fs/promises";

const outputPath = new URL("../assets/generated/prompts.json", import.meta.url);
const indexPath = new URL("../index.html", import.meta.url);

const STYLE = [
  "Premium editorial illustrative infographic for the lower visual block of a vertical HeyGen Reels card.",
  "Create one beautiful 1:1 square illustration that sits under a separate title and subtitle; this image is not a full poster.",
  "Use a close editorial composition: one large central subject or metaphor should fill 80-90% of the square frame.",
  "Avoid distant wide landscapes, tiny symbols, miniature maps, and excessive empty margins.",
  "The entire subject must fit inside the 1:1 frame with safe margins, no cropping, no cut-off objects, and a centered composition.",
  "White paper or very light editorial background, subtle depth, bold red accent #b43c34, deep navy #0f172a, restrained blue #1d4f8f.",
  "Use a single strong visual metaphor or scene built from concrete visual anchors that are explicitly supported by the beat context: people, hands, products, tools, screens, money, documents, stamps, seals, storefronts, factories, offices, marketplaces, vehicles, public spaces, physical objects, arrows, barriers, spotlights, or character action.",
  "Prefer polished vector/3D hybrid illustration, clean editorial composition, bold foreground object, simple midground/background, premium news-magazine quality.",
  "Show the idea through characters, objects, motion, confrontation, scale, and action, not through data visualization.",
  "Characters should be editorial and stylized, not photorealistic portraits; use silhouettes, diplomats, workers, leaders-at-a-distance, guards, captains, or symbolic figures when they clarify the story.",
  "Use national flags, geopolitics, ships, ports, straits, oil barrels, pipelines, military objects, maps, or country-colored props only when the beat text explicitly names a country, route, sea, port, war, sanctions, energy, or geopolitics.",
  "Never invent a country, strait, maritime route, ship, flag, oil topic, or geopolitical conflict if it is not present in the beat context.",
  "No charts, no gauges, no percentage rings, no repeated icon grids, no dense diagrams unless the beat explicitly asks for a realistic interface, document, screenshot, table, or checklist.",
  "Do not generate readable text in ordinary illustrations. Readable text is allowed only when the visual brief explicitly asks for a realistic interface, document, screenshot, table, email, or checklist, and then only as short object labels, not the main title/subtitle.",
  "No logos, no emojis, no clutter, no dark background.",
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
  if (/запрет|закрыт|блокад|ультиматум|ban|blockade/.test(joined)) return "constraint";
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
    "Visualize the central relationship and consequence using one main symbolic scene with people, objects, barriers, documents, screens, tools, money, products, places, or physical metaphors from the beat.",
    "Use real-world visual associations only from this exact beat: people, products, tools, money, documents, screens, marketplaces, offices, factories, public spaces, or other concrete objects named or strongly implied by the text.",
    "Do not introduce ships, ports, straits, country flags, maps, oil infrastructure, military checkpoints, or geopolitics unless this exact beat explicitly mentions them.",
    "Avoid graph-like output unless the story absolutely requires it, and never use gauges, rings, dashboards, or visible percentages.",
    "The generated image must not repeat the title or subtitle as text. Readable text is allowed only if this beat is a realistic interface/document/screenshot/table/checklist, and then only as short labels inside the object.",
    quote,
  ].join(" ");
}

function roleDirection(role) {
  const directions = {
    hook: "Make it a dramatic symbolic opening image with a clear central conflict, topic-specific objects or actors, and cinematic editorial energy.",
    constraint: "Show a clear physical constraint or pressure using topic-specific barriers, locked doors, blocked screens, documents, warnings, people, or objects from the beat; avoid maritime/geopolitical metaphors unless explicitly named.",
    response: "Show decisive action through topic-specific people, tools, documents, screens, or objects rather than numbers.",
    proof: "Show evidence through a concrete scene: magnifier, document, verified object, spotlight, witness-like character, or before/after object from the beat.",
    conclusion: "Show a broad topic-specific metaphor such as a crossroads, balance of forces, shifted chessboard, decision point, people, products, or competing choices.",
    "quote interpretation": "Translate words into action visually, such as a document becoming a decision, an official stamp, a blocked screen, a product moment, or a confrontation between characters.",
    analysis: "Use a clean visual metaphor that explains cause and effect with one central object scene, supported by topic-specific people or real-world objects when useful.",
  };
  return directions[role] || directions.analysis;
}

const html = await readFile(indexPath, "utf8");
const sectionMatches = [...html.matchAll(/<section\b[\s\S]*?<\/section>/gi)];
const BEATS = sectionMatches
  .map(([block]) => {
    const id = attr(block, "id");
    if (!id || !block.includes("beat-card")) return null;
    if (attr(block, "data-disabled-card") === "true") return null;
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
  aspectRatio: "1:1",
  resolution: "1K",
  prompt: `${STYLE} Card headline context: "${beat.title}". Beat role: ${beat.role}. Role direction: ${roleDirection(beat.role)} Visual brief: ${beat.visualBrief}`,
}));

await mkdir(new URL("../assets/generated/", import.meta.url), { recursive: true });
await writeFile(outputPath, `${JSON.stringify(prompts, null, 2)}\n`);

console.log(`Wrote ${prompts.length} image prompts to assets/generated/prompts.json`);
