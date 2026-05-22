#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const projectRoot = path.resolve(__dirname, '..');
const previewRoot = path.join(projectRoot, '.preview', 'youtube');
const argv = process.argv.slice(2);

const hasArg = (name) => argv.includes(`--${name}`);
const ensureArg = (args, name, value) => {
  if (hasArg(name)) return args;
  return [...args, `--${name}`, value];
};

const ensureLink = (linkPath, targetPath) => {
  if (fs.existsSync(linkPath)) {
    const stat = fs.lstatSync(linkPath);
    if (stat.isSymbolicLink() && path.resolve(path.dirname(linkPath), fs.readlinkSync(linkPath)) === targetPath) {
      return;
    }
    fs.rmSync(linkPath, {recursive: true, force: true});
  }
  fs.symlinkSync(targetPath, linkPath, 'dir');
};

fs.mkdirSync(previewRoot, {recursive: true});

let renderArgs = [
  'scripts/render-auto.mjs',
  ...argv,
];

renderArgs = ensureArg(renderArgs, 'layout', 'horizontal_youtube');
renderArgs = ensureArg(renderArgs, 'video', 'assets/input/source.mp4');
renderArgs = ensureArg(renderArgs, 'scene-plan', 'assets/input/scene-plan.generated.json');
renderArgs = ensureArg(renderArgs, 'word-cues', 'assets/input/scene-word-cues.generated.json');
renderArgs = ensureArg(renderArgs, 'out', '.preview/youtube/preview.mp4');

if (!renderArgs.includes('--dry-run')) {
  renderArgs.push('--dry-run');
}

const result = spawnSync('node', renderArgs, {
  cwd: projectRoot,
  stdio: 'inherit',
  env: {
    ...process.env,
    HYPERFRAMES_YOUTUBE_COMPOSITE_SOURCE_VIDEO: 'false',
    HYPERFRAMES_YOUTUBE_CAPTIONS: process.env.HYPERFRAMES_YOUTUBE_CAPTIONS || 'false',
    HYPERFRAMES_YOUTUBE_CHAPTER_RIBBON: process.env.HYPERFRAMES_YOUTUBE_CHAPTER_RIBBON || 'false',
    HYPERFRAMES_YOUTUBE_FPS: process.env.HYPERFRAMES_YOUTUBE_FPS || '24',
  },
});

if (result.error) {
  throw result.error;
}
if (result.status !== 0) {
  process.exit(result.status ?? 1);
}

const generatedPath = path.join(projectRoot, 'horizontal-youtube.generated.html');
const previewIndexPath = path.join(previewRoot, 'index.html');
const vendorRoot = path.join(previewRoot, 'vendor');
fs.mkdirSync(vendorRoot, {recursive: true});
fs.copyFileSync(
  path.join(projectRoot, 'node_modules', 'gsap', 'dist', 'gsap.min.js'),
  path.join(vendorRoot, 'gsap.min.js')
);

const previewHtml = fs
  .readFileSync(generatedPath, 'utf8')
  .replace('./node_modules/gsap/dist/gsap.min.js', './vendor/gsap.min.js');
fs.writeFileSync(previewIndexPath, previewHtml, 'utf8');

ensureLink(path.join(previewRoot, 'assets'), path.join(projectRoot, 'assets'));
fs.rmSync(path.join(previewRoot, 'node_modules'), {recursive: true, force: true});

fs.writeFileSync(
  path.join(previewRoot, 'meta.json'),
  `${JSON.stringify({id: 'youtube-preview', name: 'YouTube Preview'}, null, 2)}\n`,
  'utf8'
);

console.log('[youtube-preview] Prepared local preview project:');
console.log(`  ${previewIndexPath}`);
console.log('[youtube-preview] Start it with: npm run preview:youtube');
