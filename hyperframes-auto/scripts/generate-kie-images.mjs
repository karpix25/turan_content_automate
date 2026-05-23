import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

const apiKey = process.env.KIE_API_KEY;
const projectRoot = new URL("..", import.meta.url);
const indexPath = new URL("../index.html", import.meta.url);
const promptsPath = new URL("../assets/generated/prompts.json", import.meta.url);
const outputDir = new URL("../assets/generated/", import.meta.url);
const apiBase = process.env.KIE_API_BASE || "https://api.kie.ai";
const callbackUrl = process.env.KIE_CALLBACK_URL || "https://example.com/callback";
const model = process.env.KIE_IMAGE_MODEL || "gpt-image-2-text-to-image";
const aspectRatio = process.env.KIE_ASPECT_RATIO || "1:1";
const resolution = process.env.KIE_RESOLUTION || "1K";
const jobTimeoutMs = Math.max(
  60_000,
  Number(process.env.KIE_JOB_TIMEOUT_MS || 15 * 60 * 1000),
);
const concurrency = Math.max(1, Number(process.env.KIE_CONCURRENCY || 3));
const maxAttempts = Math.max(1, Number(process.env.KIE_IMAGE_MAX_ATTEMPTS || 3));
const minImageBytes = Math.max(1024, Number(process.env.KIE_IMAGE_MIN_BYTES || 16 * 1024));

if (!apiKey) {
  console.error("Missing KIE_API_KEY. Run: KIE_API_KEY=... npm run generate:images");
  process.exit(1);
}

const only = new Set(process.argv.slice(2));
const prompts = JSON.parse(await readFile(promptsPath, "utf8"));
const jobs = only.size ? prompts.filter((item) => only.has(item.id)) : prompts;

if (!jobs.length) {
  console.error(`No matching prompts. Available ids: ${prompts.map((item) => item.id).join(", ")}`);
  process.exit(1);
}

await mkdir(outputDir, { recursive: true });

async function kieFetch(endpoint, options = {}) {
  const headers = {
    Authorization: `Bearer ${apiKey}`,
    ...(options.body ? { "Content-Type": "application/json" } : {}),
    ...(options.headers || {}),
  };

  const response = await fetch(`${apiBase}${endpoint}`, {
    ...options,
    headers,
  });

  const text = await response.text();
  let body;
  try {
    body = text ? JSON.parse(text) : {};
  } catch {
    body = { raw: text };
  }

  if (!response.ok || body.code >= 400) {
    throw new Error(`${endpoint} failed: ${response.status} ${JSON.stringify(body)}`);
  }

  return body;
}

function getTaskId(body) {
  return body.data?.taskId || body.data?.task_id || body.taskId || body.task_id;
}

function getResultUrl(body) {
  const data = body.data || body;
  const response = data.response || data.result || data.output || data;
  const urls =
    response.resultUrls ||
    response.result_urls ||
    response.urls ||
    response.outputUrls ||
    response.output_urls ||
    response.images ||
    data.resultUrls ||
    data.result_urls ||
    data.outputUrls ||
    data.output_urls;

  if (Array.isArray(urls)) return urls[0];
  if (typeof urls === "string") return urls;

  const resultJson = response.resultJson || response.result_json || data.resultJson || data.result_json;
  if (typeof resultJson === "string") {
    try {
      const parsed = JSON.parse(resultJson);
      const nested = parsed.resultUrls || parsed.result_urls || parsed.urls || parsed.images;
      if (Array.isArray(nested)) return nested[0];
      if (typeof nested === "string") return nested;
    } catch {
      // ignore malformed resultJson
    }
  }

  return null;
}

async function waitForImage(taskId, label) {
  const deadline = Date.now() + jobTimeoutMs;
  let attempt = 0;
  while (Date.now() < deadline) {
    const delay = Math.min(30000, 3000 + attempt * 2000);
    await new Promise((resolve) => setTimeout(resolve, delay));
    attempt += 1;
    const details = await kieFetch(`/api/v1/jobs/recordInfo?taskId=${encodeURIComponent(taskId)}`, {
      method: "GET",
    });
    const status = details.data?.status || details.data?.state || details.status;
    const progress = details.data?.progress ?? details.progress;
    const failMsg = details.data?.failMsg || details.failMsg || "";
    const url = getResultUrl(details);
    console.log(`  ${label} status=${status || "unknown"} progress=${progress ?? "?"}`);

    if (url) return url;
    if (["failed", "error", "failure", "fail"].includes(String(status).toLowerCase())) {
      throw new Error(`Generation failed for task ${taskId}: ${failMsg || JSON.stringify(details)}`);
    }
  }

  throw new Error(`Timed out waiting for task ${taskId} after ${Math.round(jobTimeoutMs / 1000)}s`);
}

async function download(url, fileName) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`Download failed: ${response.status} ${url}`);
  const buffer = Buffer.from(await response.arrayBuffer());
  if (buffer.length < minImageBytes) {
    throw new Error(`Downloaded image is too small: ${buffer.length} bytes from ${url}`);
  }
  const filePath = path.join(outputDir.pathname, fileName);
  await writeFile(filePath, buffer);
  return filePath;
}

async function runPool(items, limit, worker) {
  const results = new Array(items.length);
  let nextIndex = 0;

  async function runWorker() {
    while (nextIndex < items.length) {
      const index = nextIndex;
      nextIndex += 1;
      results[index] = await worker(items[index], index);
    }
  }

  await Promise.all(
    Array.from({ length: Math.min(limit, items.length) }, () => runWorker()),
  );
  return results;
}

async function createImageTask(job) {
  console.log(`Creating ${job.id}...`);
  const created = await kieFetch("/api/v1/jobs/createTask", {
    method: "POST",
    body: JSON.stringify({
      model,
      callBackUrl: callbackUrl,
      input: {
        prompt: job.prompt,
        aspect_ratio: job.aspectRatio || aspectRatio,
        resolution: job.resolution || resolution,
      },
    }),
  });

  const taskId = getTaskId(created);
  if (!taskId) throw new Error(`No task id for ${job.id}: ${JSON.stringify(created)}`);
  console.log(`  ${job.id} taskId=${taskId}`);
  return { job, taskId };
}

const successfulIds = new Set();
const failedJobs = [];

console.log(`Generating ${jobs.length} KIE image(s) with concurrency=${concurrency}, attempts=${maxAttempts}`);

async function generateJob(job) {
  const errors = [];
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    try {
      console.log(`${job.id} attempt ${attempt}/${maxAttempts}`);
      const { taskId } = await createImageTask(job);
      console.log(`Waiting ${job.id}...`);
      const imageUrl = await waitForImage(taskId, job.id);
      console.log(`  ${job.id} imageUrl=${imageUrl}`);
      const saved = await download(imageUrl, job.file);
      successfulIds.add(job.id);
      console.log(`Saved ${path.relative(projectRoot.pathname, saved)}`);
      return;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      errors.push(message);
      console.error(`  ${job.id} attempt ${attempt}/${maxAttempts} failed=${message}`);
      if (attempt < maxAttempts) {
        const retryDelayMs = Math.min(30_000, 4000 * attempt);
        await new Promise((resolve) => setTimeout(resolve, retryDelayMs));
      }
    }
  }
  failedJobs.push({ id: job.id, error: errors.join(" | ") });
}

await runPool(jobs, concurrency, async (job) => {
  await generateJob(job);
});

const missingJobs = jobs.filter((job) => !successfulIds.has(job.id));
if (missingJobs.length) {
  const failureDetails = failedJobs.map((item) => `${item.id}: ${item.error}`).join(" | ");
  throw new Error(
    `KIE image generation incomplete: generated ${successfulIds.size}/${jobs.length}. ` +
    `Missing: ${missingJobs.map((job) => job.id).join(", ")}. ` +
    `Failures: ${failureDetails || "unknown"}`
  );
}

const indexHtml = await readFile(indexPath, "utf8");
const currentMatch = indexHtml.match(/data-generated-images="([^"]*)"/);
const nextIds = [...successfulIds].sort().join(",");
const nextHtml = currentMatch
  ? indexHtml.replace(/data-generated-images="[^"]*"/, `data-generated-images="${nextIds}"`)
  : indexHtml.replace("<html ", `<html data-generated-images="${nextIds}" `);
await writeFile(indexPath, nextHtml);
console.log(`Enabled generated image layers: ${nextIds}`);
if (failedJobs.length) {
  console.warn(`Retried ${failedJobs.length} image job(s): ${failedJobs.map((item) => item.id).join(", ")}`);
}
