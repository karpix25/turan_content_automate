import { readFile, rename, writeFile } from "node:fs/promises";
import { existsSync, mkdirSync } from "node:fs";
import { spawnSync } from "node:child_process";
import path from "node:path";

const projectRoot = new URL("..", import.meta.url);
const indexPath = new URL("../index.html", import.meta.url);
const inputDir = new URL("../assets/input/", import.meta.url);
const defaultSource = new URL("../assets/input/source.mp4", import.meta.url);

const args = process.argv.slice(2);

function getArg(name) {
  const index = args.indexOf(`--${name}`);
  if (index === -1) return "";
  const next = args[index + 1];
  return next && !next.startsWith("--") ? next : "";
}

function hasFlag(name) {
  return args.includes(`--${name}`);
}

function resolveFromProject(value) {
  if (!value) return "";
  return path.isAbsolute(value) ? value : path.resolve(projectRoot.pathname, value);
}

function runFfprobe(params, label) {
  const result = spawnSync("ffprobe", params, { encoding: "utf8" });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`${label} failed: ${result.stderr || result.stdout}`);
  }
  return result.stdout.trim();
}

function readAudioCodec(filePath) {
  try {
    const raw = runFfprobe(
      [
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=codec_name",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        filePath,
      ],
      "ffprobe audio codec",
    );
    return raw.trim().toLowerCase();
  } catch {
    return "";
  }
}

function runFfmpeg(params, label) {
  const result = spawnSync("ffmpeg", params, { encoding: "utf8" });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    throw new Error(`${label} failed: ${result.stderr || result.stdout}`);
  }
}

async function normalizeVideoForRendering(inputPath, outputPath) {
  const tempPath = `${outputPath}.normalized.tmp.mp4`;
  const audioCodec = readAudioCodec(inputPath);
  const audioArgs = audioCodec === "aac" ? ["-c:a", "copy"] : ["-c:a", "aac", "-b:a", "256k"];
  runFfmpeg(
    [
      "-y",
      "-i",
      inputPath,
      "-map",
      "0:v:0",
      "-map",
      "0:a?",
      "-c:v",
      "libx264",
      "-preset",
      "veryfast",
      "-pix_fmt",
      "yuv420p",
      "-r",
      "30",
      "-g",
      "30",
      "-keyint_min",
      "30",
      "-sc_threshold",
      "0",
      "-movflags",
      "+faststart",
      ...audioArgs,
      tempPath,
    ],
    "ffmpeg normalize source video",
  );
  await rename(tempPath, outputPath);
}

function readDuration(filePath) {
  const raw = runFfprobe(
    ["-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", filePath],
    "ffprobe duration",
  );
  const duration = Number(raw);
  if (!Number.isFinite(duration) || duration <= 0) {
    throw new Error(`Could not read video duration from ${filePath}`);
  }
  return duration;
}

function parseRate(value) {
  const [num, den = "1"] = String(value).split("/").map(Number);
  if (!Number.isFinite(num) || !Number.isFinite(den) || den === 0) return 25;
  return Math.round(num / den);
}

function readFps(filePath) {
  const raw = runFfprobe(
    [
      "-v",
      "error",
      "-select_streams",
      "v:0",
      "-show_entries",
      "stream=avg_frame_rate",
      "-of",
      "default=noprint_wrappers=1:nokey=1",
      filePath,
    ],
    "ffprobe fps",
  );
  return parseRate(raw);
}

function readDimensions(filePath) {
  const raw = runFfprobe(
    [
      "-v",
      "error",
      "-select_streams",
      "v:0",
      "-show_entries",
      "stream=width,height",
      "-of",
      "csv=p=0:s=x",
      filePath,
    ],
    "ffprobe dimensions",
  );
  const [width, height] = raw.split("x").map(Number);
  return { width, height };
}

function replaceOne(html, pattern, value, label) {
  if (!pattern.test(html)) {
    throw new Error(`Could not update ${label} in index.html`);
  }
  return html.replace(pattern, value);
}

const inputVideo = resolveFromProject(getArg("video"));
const keepImages = hasFlag("keep-images");

mkdirSync(inputDir, { recursive: true });

if (inputVideo) {
  if (!existsSync(inputVideo)) throw new Error(`Video not found: ${inputVideo}`);
  await normalizeVideoForRendering(inputVideo, defaultSource.pathname);
}

if (!existsSync(defaultSource)) {
  throw new Error(`No source video found at ${defaultSource.pathname}. Pass --video /path/to/file.mp4 first.`);
}

const duration = readDuration(defaultSource.pathname);
const fps = readFps(defaultSource.pathname);
const { width, height } = readDimensions(defaultSource.pathname);
const durationText = duration.toFixed(3);

let html = await readFile(indexPath, "utf8");

html = replaceOne(
  html,
  /(<div\s+id="main"[\s\S]*?data-duration=")[^"]+(")/,
  `$1${durationText}$2`,
  "root data-duration",
);
html = replaceOne(
  html,
  /(<video\s+id="source-video"[\s\S]*?data-duration=")[^"]+(")/,
  `$1${durationText}$2`,
  "source video data-duration",
);
html = html.replace(
  /(<video\s+id="source-video"[\s\S]*?data-volume=")[^"]+(")/,
  (_match, before, after) => `${before}0${after}`,
);
html = replaceOne(
  html,
  /(<video\s+id="source-video"[\s\S]*?data-has-audio=")[^"]+(")/,
  "$1false$2",
  "source video data-has-audio",
);
html = html.replace(
  /(<video\s+id="source-video"[\s\S]*?src="[^"]+"[\s\S]*?)(\s+playsinline)/,
  (match, before, after) => (/\smuted(\s|>)/.test(match) ? match : `${before}\n        muted${after}`),
);
html = replaceOne(html, /(\bdata-fps=")[^"]+(")/, `$1${fps}$2`, "data-fps");
html = replaceOne(html, /const totalDuration = [0-9.]+;/, `const totalDuration = ${durationText};`, "totalDuration");

if (!keepImages) {
  html = replaceOne(
    html,
    /data-generated-images="[^"]*"/,
    'data-generated-images=""',
    "generated image ids",
  );
}

await writeFile(indexPath, html);

console.log("[prepare-heygen-video] Updated source video metadata:");
console.log(`  source: ${defaultSource.pathname}`);
console.log(`  duration: ${durationText}s`);
console.log(`  fps: ${fps}`);
console.log(`  dimensions: ${width}x${height}`);
console.log("  normalized: h264/yuv420p, 30fps, keyframe interval 30");
if (width > height) {
  console.warn("  warning: source video is not vertical; 9:16 output will crop/cover it.");
}
if (!keepImages) {
  console.log("  generated image slots reset; run KIE_API_KEY=... npm run generate:visuals for this video.");
}
