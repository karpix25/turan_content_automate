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
  if (index === -1) {
    return fallback;
  }

  const next = argv[index + 1];
  if (!next || next.startsWith('--')) {
    return fallback;
  }

  return next;
};

const hasFlag = (name) => argv.includes(`--${name}`);

const resolveFromProject = (inputPath) =>
  path.isAbsolute(inputPath) ? inputPath : path.resolve(projectRoot, inputPath);

const probeVideoDurationSec = (filePath) => {
  const result = spawnSync(
    'ffprobe',
    [
      '-v',
      'error',
      '-show_entries',
      'format=duration',
      '-of',
      'default=noprint_wrappers=1:nokey=1',
      filePath,
    ],
    {encoding: 'utf8'},
  );

  if (result.error || result.status !== 0) {
    return 0;
  }

  const duration = Number(String(result.stdout || '').trim());
  return Number.isFinite(duration) && duration > 0 ? duration : 0;
};

const defaultVideo = '../hf-montage-test/source_optimized_45s.mp4';
const defaultScenePlan = '../hf-montage-test/data/scene-plan.generated.json';
const defaultWordCues = '../hf-montage-test/data/scene-word-cues.generated.json';
const defaultOutput = '../hf-montage-test/renders/remotion-auto.mp4';

const sourceVideoPath = resolveFromProject(getArgValue('video', defaultVideo));
const scenePlanPath = resolveFromProject(getArgValue('scene-plan', defaultScenePlan));
const wordCuesPath = resolveFromProject(getArgValue('word-cues', defaultWordCues));
const outputPath = resolveFromProject(getArgValue('out', defaultOutput));
const themePreset = getArgValue('theme', 'youtubeBusiness');
const montagePreset = getArgValue('preset', 'balanced');
const cueWindowSec = Number(getArgValue('cue-window-sec', '0.95'));
const codec = getArgValue('codec', 'h264');
const maxDurationSecArg = Number(getArgValue('max-duration-sec', '0'));
const dryRun = hasFlag('dry-run');

const assertExists = (filePath, label) => {
  if (!fs.existsSync(filePath)) {
    throw new Error(`${label} not found: ${filePath}`);
  }
};

assertExists(sourceVideoPath, 'Video file');
assertExists(scenePlanPath, 'Scene plan file');
assertExists(wordCuesPath, 'Word cues file');

const publicInputDir = path.join(projectRoot, 'public', 'input');
fs.mkdirSync(publicInputDir, {recursive: true});

const videoExtension = path.extname(sourceVideoPath) || '.mp4';
const copiedVideoName = `source${videoExtension}`;
const copiedVideoPath = path.join(publicInputDir, copiedVideoName);
const copiedScenePlanPath = path.join(publicInputDir, 'scene-plan.generated.json');
const copiedWordCuesPath = path.join(publicInputDir, 'scene-word-cues.generated.json');

fs.copyFileSync(sourceVideoPath, copiedVideoPath);
fs.copyFileSync(scenePlanPath, copiedScenePlanPath);
fs.copyFileSync(wordCuesPath, copiedWordCuesPath);

const normalizeMode = (value) => {
  const raw = String(value || '').toLowerCase().trim();
  if (['mini', 'lower-third', 'lower_third', 'overlay', 'side'].includes(raw)) return 'mini';
  return 'full';
};

const scenesRaw = fs.readFileSync(copiedScenePlanPath, 'utf8');
const scenesParsed = JSON.parse(scenesRaw);
const scenes = Array.isArray(scenesParsed)
  ? scenesParsed.map((scene) => {
      const normalized = {...scene};
      normalized.mode = normalizeMode(scene?.mode);
      delete normalized.chartType;
      delete normalized.subtitle;
      return normalized;
    })
  : scenesParsed;

if (!Array.isArray(scenes) || scenes.length === 0) {
  throw new Error('Scene plan is empty or invalid JSON array.');
}

fs.writeFileSync(copiedScenePlanPath, `${JSON.stringify(scenes, null, 2)}\n`, 'utf8');

const maxEndSec = scenes.reduce((max, scene) => {
  const end = Number(scene?.end);
  return Number.isFinite(end) ? Math.max(max, end) : max;
}, 0);

const videoDurationSec = probeVideoDurationSec(sourceVideoPath);
const detectedDurationSec = videoDurationSec > 0 ? videoDurationSec : maxEndSec > 0 ? maxEndSec : 60;
const maxDurationSec = Number.isFinite(maxDurationSecArg) ? maxDurationSecArg : 0;
const durationSec =
  maxDurationSec > 0 ? Math.min(detectedDurationSec, maxDurationSec) : detectedDurationSec;

const outputDir = path.dirname(outputPath);
fs.mkdirSync(outputDir, {recursive: true});

const props = {
  videoFile: `input/${copiedVideoName}`,
  scenePlanFile: 'input/scene-plan.generated.json',
  wordCuesFile: 'input/scene-word-cues.generated.json',
  durationSec,
  cueWindowSec: Number.isFinite(cueWindowSec) ? cueWindowSec : 0.95,
  themePreset,
  montagePreset,
};

const renderArgs = [
  'remotion',
  'render',
  'src/index.ts',
  'AutoMontage',
  outputPath,
  '--codec',
  codec,
  '--props',
  JSON.stringify(props),
  '--overwrite',
];

console.log('[render-auto] Prepared input files:');
console.log(`  video: ${sourceVideoPath}`);
console.log(`  scene-plan: ${scenePlanPath}`);
console.log(`  word-cues: ${wordCuesPath}`);
console.log(`  output: ${outputPath}`);
console.log(`  theme: ${themePreset}`);
console.log(`  preset: ${montagePreset}`);
console.log(`  duration: ${durationSec}s`);
console.log(`  video-duration: ${videoDurationSec || 'unavailable'}s`);
console.log(`  scene-plan-max-end: ${maxEndSec || 'unavailable'}s`);

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
