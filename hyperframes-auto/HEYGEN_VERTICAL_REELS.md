# HeyGen Vertical Reels Rule

Use this rule for every vertical HeyGen source video in this project.

## Format

- Composition is always `1080x1920`.
- Output is always `9:16`.
- The HeyGen video remains the base layer and keeps its original audio.
- Overlays are editorial cutaways, not full replacement scenes.

## Director

- Target overlay coverage is about `50%` of the video duration.
- Keep clean avatar/video gaps between cutaways when possible.
- Prefer avatar visibility over excessive slide density.
- Every overlay must advance the spoken story: hook, conflict, consequence, proof, or conclusion.

## Card Design

- All slide cards use one standard size:
  - width: `100%` of the overlay safe area
  - height: `70%`
  - centered in the frame
  - same padding, radius, visual block height, and vertical centering
- Do not vary slide height by beat type.
- Keep the top of the card as deterministic HTML/CSS:
  - kicker
  - headline
  - subtitle
  - quote attribution if needed
- If a card is a quote or author interpretation, it must name the source/context, e.g. `Авторский перевод дипломатического смысла`.
- Remove low-value footers, meters, and status boxes once AI visual art is available.

## Visual Block

- The lower visual block is the main infographic.
- Generate this block as an image when possible.
- The generated image must:
  - stay on a white or near-white background
  - match the red/navy editorial style
  - avoid repeating the card headline/subtitle
  - avoid tiny labels and decorative clutter
  - visualize relationships and consequences, not isolated nouns

## AI Image Pipeline

1. Build or update the HTML cards.
2. Run:

   ```bash
   npm run generate:prompts
   ```

3. Generate the visual blocks through Kie.ai GPT Image 2:

   ```bash
   KIE_API_KEY=... npm run generate:images
   ```

4. The image generator saves `assets/generated/beat-N.png` and enables those IDs in `data-generated-images`.
5. Run:

   ```bash
   npm run check
   ```

## Prompt Rule

Prompts are generated from the actual card content in `index.html`.

Each prompt should produce only the lower infographic image, because the title/subtitle remain HTML.
The prompt should follow this semantic model:

```text
subject -> action -> obstacle -> result
```

For weak visuals, improve the `data-visual-brief` on the corresponding `<section>` instead of redesigning the whole card.
