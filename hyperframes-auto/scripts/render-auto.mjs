#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = path.resolve(__dirname, '..');
const argv = process.argv.slice(2);

const getArgValue = (name, fallback) => {
  const index = argv.indexOf(`--${name}`);
  if (index === -1) return fallback;
  const next = argv[index + 1];
  if (!next || next.startsWith('--')) return fallback;
  return next;
};

const hasFlag = (name) => argv.includes(`--${name}`);
const resolveFromProject = (inputPath) =>
  path.isAbsolute(inputPath) ? inputPath : path.resolve(projectRoot, inputPath);

const defaultVideo = '../hf-montage-test/source_optimized_45s.mp4';
const defaultScenePlan = '../hf-montage-test/data/scene-plan.generated.json';
const defaultWordCues = '../hf-montage-test/data/scene-word-cues.generated.json';
const defaultOutput = '../hf-montage-test/renders/hyperframes-auto.mp4';

const sourceVideoPath = resolveFromProject(getArgValue('video', defaultVideo));
const scenePlanPath = resolveFromProject(getArgValue('scene-plan', defaultScenePlan));
const wordCuesPath = resolveFromProject(getArgValue('word-cues', defaultWordCues));
const outputPath = resolveFromProject(getArgValue('out', defaultOutput));
const maxDurationSecArg = Number(getArgValue('max-duration-sec', '0'));
const fps = Number(getArgValue('fps', '30'));
const dryRun = hasFlag('dry-run');

const assertExists = (filePath, label) => {
  if (!fs.existsSync(filePath)) {
    throw new Error(`${label} not found: ${filePath}`);
  }
};

const normalizeText = (value) => String(value || '').replace(/\s+/g, ' ').trim();

const trimOpener = (value) => {
  const clean = normalizeText(value).replace(/["'«»]+/g, '').trim();
  if (!clean) return '';
  const words = clean.split(' ');
  return words.length > 6 ? words.slice(0, 6).join(' ') : clean;
};

const pickSceneOpener = (scene) => {
  if (!scene || typeof scene !== 'object') return '';
  const openerField = trimOpener(normalizeText(scene.chapterOpener || scene.opener));
  if (openerField) return openerField;
  const candidates = [
    normalizeText(scene.chapterTitle),
    normalizeText(scene.title),
    normalizeText(scene.keyword),
    ...(Array.isArray(scene.titleLines) ? scene.titleLines.map(normalizeText) : []),
    normalizeText(scene.insight),
    normalizeText(scene.cta),
  ].filter(Boolean);
  return trimOpener(candidates[0] || '');
};

const escapeHtml = (value) =>
  String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');

const assertFinitePositive = (value, fallback) =>
  Number.isFinite(value) && value > 0 ? value : fallback;

const readJsonArray = (filePath, label) => {
  const parsed = JSON.parse(fs.readFileSync(filePath, 'utf8'));
  if (!Array.isArray(parsed)) {
    throw new Error(`${label} must be a JSON array: ${filePath}`);
  }
  return parsed;
};

assertExists(sourceVideoPath, 'Video file');
assertExists(scenePlanPath, 'Scene plan file');
assertExists(wordCuesPath, 'Word cues file');

const assetsInputDir = path.join(projectRoot, 'assets', 'input');
fs.mkdirSync(assetsInputDir, {recursive: true});

const videoExtension = path.extname(sourceVideoPath) || '.mp4';
const copiedVideoName = `source${videoExtension}`;
const copiedVideoPath = path.join(assetsInputDir, copiedVideoName);
const copiedScenePlanPath = path.join(assetsInputDir, 'scene-plan.generated.json');
const copiedWordCuesPath = path.join(assetsInputDir, 'scene-word-cues.generated.json');

fs.copyFileSync(sourceVideoPath, copiedVideoPath);
fs.copyFileSync(scenePlanPath, copiedScenePlanPath);
fs.copyFileSync(wordCuesPath, copiedWordCuesPath);

const scenes = readJsonArray(copiedScenePlanPath, 'Scene plan')
  .map((scene) => ({
    ...scene,
    start: Number(scene?.start),
    end: Number(scene?.end),
  }))
  .filter((scene) => Number.isFinite(scene.start) && Number.isFinite(scene.end) && scene.end > scene.start)
  .sort((a, b) => a.start - b.start);

if (!scenes.length) {
  throw new Error('Scene plan has no valid timed scenes.');
}

fs.writeFileSync(copiedScenePlanPath, `${JSON.stringify(scenes, null, 2)}\n`, 'utf8');

const detectedDurationSec = scenes.reduce((max, scene) => Math.max(max, scene.end), 0);
const maxDurationSec = Number.isFinite(maxDurationSecArg) ? maxDurationSecArg : 0;
const durationSec = maxDurationSec > 0 ? Math.min(detectedDurationSec, maxDurationSec) : detectedDurationSec;
const rootDuration = assertFinitePositive(durationSec, 1);
const renderFps = Math.round(assertFinitePositive(fps, 30));

const overlayClips = scenes
  .map((scene, index) => {
    const text = pickSceneOpener(scene);
    if (!text) return '';
    const visibleDuration = Math.min(3, Math.max(0.5, scene.end - scene.start));
    return `
      <div
        id="opener-${index}"
        class="clip opener"
        data-start="${scene.start.toFixed(3)}"
        data-duration="${visibleDuration.toFixed(3)}"
        data-track-index="1"
      >
        <div class="opener-text">${escapeHtml(text)}</div>
      </div>`;
  })
  .filter(Boolean)
  .join('\n');

const timelineTweens = scenes
  .map((scene, index) => {
    const text = pickSceneOpener(scene);
    if (!text) return '';
    const visibleDuration = Math.min(3, Math.max(0.5, scene.end - scene.start));
    const fadeOutAt = Math.max(scene.start + 0.5, scene.start + visibleDuration - 0.35);
    return `
      tl.fromTo("#opener-${index}", { opacity: 0, y: 18 }, { opacity: 1, y: 0, duration: 0.34, ease: "power3.out" }, ${scene.start.toFixed(3)});
      tl.to("#opener-${index}", { opacity: 0, y: -10, duration: 0.32, ease: "power2.in" }, ${fadeOutAt.toFixed(3)});`;
  })
  .filter(Boolean)
  .join('\n');

const html = `<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=1920, height=1080" />
    <script src="./node_modules/gsap/dist/gsap.min.js"></script>
    <style>
      * { margin: 0; padding: 0; box-sizing: border-box; }
      html, body {
        width: 1920px;
        height: 1080px;
        overflow: hidden;
        background: #000;
        font-family: Montserrat, Arial, sans-serif;
      }
      #main {
        position: relative;
        width: 1920px;
        height: 1080px;
        overflow: hidden;
        background: #000;
      }
      .background-video {
        position: absolute;
        inset: 0;
        width: 100%;
        height: 100%;
        object-fit: cover;
        z-index: 0;
      }
      .opener {
        position: absolute;
        left: 50%;
        bottom: 7.5%;
        max-width: 86%;
        padding: 18px 28px;
        border-radius: 20px;
        border: 1px solid rgba(255, 255, 255, 0.16);
        background: rgba(0, 0, 0, 0.56);
        transform: translateX(-50%);
        backdrop-filter: blur(4px);
        z-index: 2;
        pointer-events: none;
      }
      .opener-text {
        color: #fff;
        font-weight: 800;
        font-size: 58px;
        line-height: 1.15;
        text-align: center;
        -webkit-text-stroke: 2px rgba(0, 0, 0, 0.75);
        paint-order: stroke fill;
        text-shadow: 0 2px 8px rgba(0, 0, 0, 0.45);
        word-break: break-word;
        overflow-wrap: anywhere;
      }
    </style>
  </head>
  <body>
    <div
      id="main"
      data-composition-id="main"
      data-start="0"
      data-duration="${rootDuration.toFixed(3)}"
      data-fps="${renderFps}"
      data-width="1920"
      data-height="1080"
    >
      <video
        id="source-video"
        class="clip background-video"
        data-start="0"
        data-duration="${rootDuration.toFixed(3)}"
        data-track-index="0"
        src="./assets/input/${escapeHtml(copiedVideoName)}"
        muted
        playsinline
      ></video>
${overlayClips}
    </div>

    <script>
      window.__timelines = window.__timelines || {};
      const tl = gsap.timeline({ paused: true });
${timelineTweens}
      window.__timelines.main = tl;
    </script>
  </body>
</html>
`;

fs.writeFileSync(path.join(projectRoot, 'index.html'), html, 'utf8');

const outputDir = path.dirname(outputPath);
fs.mkdirSync(outputDir, {recursive: true});

const renderArgs = [
  'hyperframes',
  'render',
  '--output',
  outputPath,
  '--fps',
  String(renderFps),
  '--quality',
  'standard',
];

console.log('[render-auto] Prepared Hyperframes input files:');
console.log(`  video: ${sourceVideoPath}`);
console.log(`  scene-plan: ${scenePlanPath}`);
console.log(`  word-cues: ${wordCuesPath}`);
console.log(`  output: ${outputPath}`);
console.log(`  duration: ${rootDuration}s`);

if (dryRun) {
  console.log('[render-auto] Dry run mode enabled. Render command:');
  console.log(`npx ${renderArgs.join(' ')}`);
  process.exit(0);
}

const result = spawnSync('npx', renderArgs, {
  cwd: projectRoot,
  stdio: 'inherit',
});

if (result.error) {
  throw result.error;
}

process.exit(result.status ?? 1);
