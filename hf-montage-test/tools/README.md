# Smart Montage Pipeline

## What it does

`smart_montage_pipeline.py` builds scene plan automatically:

1. Deepgram transcription (`/v1/listen`)
2. Semantic blocks from transcript (`5-10` sentences each by default)
3. Scene plan synthesis via LLM (or deterministic fallback)
3. Injects generated plan into `index.html` (`<script id="scene-plan">`)

It also writes semantic blocks to:
- `data/semantic-blocks.generated.json`

## Required env vars

- `DEEPGRAM_API_KEY`
- `OPENROUTER_API_KEY` or `OPENAI_API_KEY` or `LLM_API_KEY` (for LLM mode)

Optional:

- `LLM_BASE_URL` (default: `https://api.openai.com/v1`)
- `LLM_MODEL` (default fallback in script: `google/gemini-3.5-flash`)
- `OPENROUTER_SITE_URL` and `OPENROUTER_APP_NAME` (optional OpenRouter headers)

If no LLM key is set, the script auto-falls back to deterministic planning.
Use `--strict-llm` if you want to fail instead of fallback.

## Run (with LLM)

```bash
cd hf-montage-test
python3 tools/smart_montage_pipeline.py \
  --video source_optimized_45s.mp4 \
  --index index.html \
  --language ru \
  --deepgram-model nova-3 \
  --utt-split 0.65 \
  --llm-model google/gemini-3.5-flash \
  --max-scenes 8 \
  --block-min-sentences 5 \
  --block-max-sentences 10
```

## Run (with OpenRouter + Gemini)

```bash
cd hf-montage-test
python3 tools/smart_montage_pipeline.py \
  --video source_optimized_45s.mp4 \
  --index index.html \
  --language ru \
  --deepgram-model nova-3 \
  --utt-split 0.65 \
  --llm-model google/gemini-3.5-flash \
  --max-scenes 8 \
  --block-min-sentences 5 \
  --block-max-sentences 10 \
  --strict-llm
```

## Run (without LLM, fallback planner)

```bash
cd hf-montage-test
python3 tools/smart_montage_pipeline.py \
  --video source_optimized_45s.mp4 \
  --index index.html \
  --language ru \
  --utt-split 0.65 \
  --block-min-sentences 5 \
  --block-max-sentences 10 \
  --skip-llm
```

## Render after generation

```bash
cd hf-montage-test
npx hyperframes render --quality draft --output renders/smart-montage-draft.mp4
```
