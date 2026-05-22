#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';

const argv = process.argv.slice(2);

const getArg = (name, fallback = '') => {
  const index = argv.indexOf(`--${name}`);
  if (index === -1) return fallback;
  const next = argv[index + 1];
  return next && !next.startsWith('--') ? next : fallback;
};

const inputPath = getArg('input');
const outputPath = getArg('out');

if (!inputPath || !outputPath) {
  console.error('Usage: node scripts/whisper-to-deepgram.mjs --input whisper.json --out deepgram-like.json');
  process.exit(2);
}

const whisper = JSON.parse(fs.readFileSync(inputPath, 'utf8'));
const segments = Array.isArray(whisper.segments) ? whisper.segments : [];
const transcript = String(whisper.text || segments.map((segment) => segment.text || '').join(' ')).replace(/\s+/g, ' ').trim();

const words = [];
const sentences = [];

for (const [segmentIndex, segment] of segments.entries()) {
  const start = Number(segment.start);
  const end = Number(segment.end);
  const text = String(segment.text || '').replace(/\s+/g, ' ').trim();
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start || !text) {
    continue;
  }

  sentences.push({
    text,
    start: Number(start.toFixed(2)),
    end: Number(end.toFixed(2)),
  });

  const tokens = text.match(/[\p{L}\p{N}%.,!?;:()"'«»—-]+/gu) || [];
  const duration = Math.max(0.1, end - start);
  const step = duration / Math.max(1, tokens.length);
  for (const [tokenIndex, token] of tokens.entries()) {
    const tokenStart = start + step * tokenIndex;
    const tokenEnd = tokenIndex === tokens.length - 1 ? end : start + step * (tokenIndex + 1);
    const cleanWord = token.replace(/^[^\p{L}\p{N}]+|[^\p{L}\p{N}]+$/gu, '') || token;
    words.push({
      word: cleanWord.toLowerCase(),
      start: Number(tokenStart.toFixed(2)),
      end: Number(tokenEnd.toFixed(2)),
      confidence: Number(segment.avg_logprob ?? 0),
      punctuated_word: token,
    });
  }
}

const duration = Number(whisper.duration) || Math.max(0, ...segments.map((segment) => Number(segment.end) || 0));
const paragraphs = [];
const paragraphSize = 5;
for (let index = 0; index < sentences.length; index += paragraphSize) {
  const paragraphSentences = sentences.slice(index, index + paragraphSize);
  if (!paragraphSentences.length) continue;
  paragraphs.push({
    sentences: paragraphSentences,
    start: paragraphSentences[0].start,
    end: paragraphSentences[paragraphSentences.length - 1].end,
    num_words: words.filter((word) => word.start >= paragraphSentences[0].start && word.end <= paragraphSentences[paragraphSentences.length - 1].end).length,
  });
}

const deepgramLike = {
  metadata: {
    transaction_key: 'local-whisper',
    request_id: 'local-whisper',
    created: new Date().toISOString(),
    duration,
    channels: 1,
    models: ['openai-whisper-local'],
    model_info: {
      'openai-whisper-local': {
        name: whisper.model || 'whisper',
        version: 'local',
        arch: 'whisper',
      },
    },
  },
  results: {
    channels: [
      {
        alternatives: [
          {
            transcript,
            confidence: 0,
            words,
            paragraphs: {
              transcript,
              paragraphs,
            },
          },
        ],
      },
    ],
  },
};

fs.mkdirSync(path.dirname(outputPath), {recursive: true});
fs.writeFileSync(outputPath, `${JSON.stringify(deepgramLike, null, 2)}\n`, 'utf8');

console.log('[whisper-to-deepgram] Wrote transcript:');
console.log(`  input: ${inputPath}`);
console.log(`  output: ${outputPath}`);
console.log(`  duration: ${duration.toFixed(2)}s`);
console.log(`  segments: ${segments.length}`);
console.log(`  words: ${words.length}`);
