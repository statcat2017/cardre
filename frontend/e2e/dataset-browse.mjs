import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { existsSync } from "node:fs";
import { mkdir, mkdtemp, readdir, rm, stat } from "node:fs/promises";

import { chromium } from "playwright";

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = resolve(frontendRoot, "..");
const python =
  process.env.CARDRE_PYTHON ??
  (existsSync(join(repoRoot, ".venv", "bin", "python"))
    ? join(repoRoot, ".venv", "bin", "python")
    : "python3");
const datasetPath = join(repoRoot, "datasets", "german_credit", "german_credit.parquet");
const outputDir = process.env.CARDRE_BROWSER_OUTPUT_DIR;
const processes = [];
const processLogs = new Map();
let browser;
let temporaryRoot;

async function freePort() {
  const server = createServer();
  await new Promise((resolveListen, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolveListen);
  });
  const address = server.address();
  assert.ok(address && typeof address !== "string");
  await new Promise((resolveClose, reject) => {
    server.close((error) => (error ? reject(error) : resolveClose()));
  });
  return address.port;
}

function start(command, args, cwd, env, name) {
  const child = spawn(command, args, {
    cwd,
    env,
    stdio: ["ignore", "pipe", "pipe"],
  });
  processes.push(child);
  processLogs.set(name, "");
  for (const stream of [child.stdout, child.stderr]) {
    stream.setEncoding("utf8");
    stream.on("data", (chunk) => {
      const current = processLogs.get(name) ?? "";
      processLogs.set(name, (current + chunk).slice(-30_000));
    });
  }
  return child;
}

async function waitFor(url, child, name) {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    if (child.exitCode !== null) {
      throw new Error(name + " exited before becoming ready.\n" + processLogs.get(name));
    }
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
      // The process may still be starting.
    }
    await new Promise((resolveDelay) => setTimeout(resolveDelay, 250));
  }
  throw new Error(name + " did not become ready.\n" + processLogs.get(name));
}

async function stop(child) {
  if (child.exitCode !== null || child.signalCode !== null) return;
  const exited = new Promise((resolveExit) => child.once("exit", resolveExit));
  child.kill("SIGTERM");
  await Promise.race([exited, new Promise((resolveDelay) => setTimeout(resolveDelay, 5_000))]);
  if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
}

async function apiJson(url, init) {
  const response = await fetch(url, init);
  const body = await response.json();
  assert.ok(
    response.ok,
    (init?.method ?? "GET") +
      " " +
      url +
      " returned " +
      response.status +
      ": " +
      JSON.stringify(body),
  );
  return body;
}

async function fillStepField(card, name, value) {
  await card.locator("label").filter({ hasText: name }).locator("input").fill(value);
}

async function saveStep(page, card, planVersionId) {
  const saved = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return (
      response.request().method() === "PATCH" &&
      url.pathname.includes("/plan-versions/" + planVersionId + "/steps/")
    );
  });
  await card.getByRole("button", { name: "Save", exact: true }).click();
  const response = await saved;
  assert.equal(response.status(), 200, await response.text());
}

async function downloadExport(page, fileName, mediaType) {
  const responsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return (
      response.request().method() === "GET" &&
      url.pathname.includes("/exports/") &&
      url.pathname.endsWith("/download")
    );
  });
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download " + fileName }).click();
  const [response, download] = await Promise.all([responsePromise, downloadPromise]);
  assert.equal(response.status(), 200);
  assert.ok(response.headers()["content-type"].startsWith(mediaType));
  assert.equal(download.suggestedFilename(), fileName);
  assert.equal(await download.failure(), null, fileName + " download should complete");
}

async function run() {
  assert.ok(existsSync(datasetPath), "Expected fixture dataset at " + datasetPath);
  temporaryRoot = await mkdtemp(join(tmpdir(), "cardre-browse-e2e-"));
  const registryPath = join(temporaryRoot, "registry", "projects.json");
  const projectRoot = join(temporaryRoot, "project.cardre");
  const apiPort = await freePort();
  const webPort = await freePort();
  const apiBase = "http://127.0.0.1:" + apiPort;
  const webBase = "http://127.0.0.1:" + webPort;

  const sidecar = start(
    python,
    ["-m", "sidecar"],
    repoRoot,
    {
      ...process.env,
      CARDRE_API_HOST: "127.0.0.1",
      CARDRE_API_PORT: String(apiPort),
      CARDRE_CORS_ORIGINS: webBase,
      CARDRE_REGISTRY_PATH: registryPath,
    },
    "sidecar",
  );
  const vite = start(
    process.execPath,
    [
      join(frontendRoot, "node_modules", "vite", "bin", "vite.js"),
      "--host",
      "127.0.0.1",
      "--port",
      String(webPort),
      "--strictPort",
    ],
    frontendRoot,
    process.env,
    "vite",
  );

  try {
    await Promise.all([
      waitFor(apiBase + "/health", sidecar, "sidecar"),
      waitFor(webBase, vite, "vite"),
    ]);

    browser = await chromium.launch({
      headless: true,
      ...(process.env.CARDRE_CHROMIUM_EXECUTABLE
        ? { executablePath: process.env.CARDRE_CHROMIUM_EXECUTABLE }
        : {}),
    });
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    await page.addInitScript((url) => {
      window.__API_URL__ = url;
    }, apiBase);
    await page.goto(webBase);

    await page.getByLabel("Project root").fill(projectRoot);
    await page.getByLabel("Project name").fill("Dataset Browse E2E");
    const projectResponse = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" && new URL(response.url()).pathname === "/projects",
    );
    await page.getByRole("button", { name: "Create Project", exact: true }).click();
    const project = await (await projectResponse).json();
    assert.equal(project.name, "Dataset Browse E2E");

    await page.getByPlaceholder("New plan name").fill("German Credit");
    const planResponse = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname.endsWith("/plans"),
    );
    await page.getByRole("button", { name: "Create plan", exact: true }).click();
    const plan = await (await planResponse).json();

    const filePicker = page.locator("#parquet-file-picker");
    const invalidUpload = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname.endsWith("/datasets"),
    );
    await filePicker.setInputFiles({
      name: "invalid.parquet",
      mimeType: "application/octet-stream",
      buffer: Buffer.from("not a parquet file"),
    });
    const invalidResponse = await invalidUpload;
    assert.equal(invalidResponse.status(), 422);
    assert.equal((await invalidResponse.json()).detail.code, "DATASET_INVALID");
    await page.getByRole("alert").waitFor();
    assert.equal(
      await page.getByRole("button", { name: "Generate launch pathway" }).isDisabled(),
      true,
    );
    const versionsAfterInvalidUpload = await apiJson(
      apiBase + "/projects/" + project.project_id + "/plans/" + plan.plan_id + "/versions",
    );
    assert.deepEqual(versionsAfterInvalidUpload.versions, []);
    const rejectedDatasetFiles = await readdir(join(projectRoot, "datasets")).catch((error) => {
      if (error.code === "ENOENT") return [];
      throw error;
    });
    assert.deepEqual(rejectedDatasetFiles, []);

    const validUpload = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname.endsWith("/datasets"),
    );
    await filePicker.setInputFiles(datasetPath);
    assert.equal((await validUpload).status(), 201);
    await page.getByRole("status").getByText("Ready: german_credit.parquet").waitFor();
    await filePicker.dispatchEvent("cancel");
    await page.getByRole("status").getByText("Ready: german_credit.parquet").waitFor();

    await page.getByPlaceholder("class").fill("class");
    await page.getByPlaceholder("good").fill("good");
    await page.getByPlaceholder("bad").fill("bad");
    const canonicalResponse = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname.endsWith("/canonical-version"),
    );
    await page.getByRole("button", { name: "Generate launch pathway" }).click();
    const planVersion = await (await canonicalResponse).json();
    assert.equal(planVersion.is_committed, false);

    const versionStepsUrl =
      apiBase +
      "/projects/" +
      project.project_id +
      "/plan-versions/" +
      planVersion.plan_version_id +
      "/steps";
    const versionSteps = await apiJson(versionStepsUrl);
    const sourcePath = versionSteps[0].params.source_path;
    assert.equal(dirname(sourcePath), join(projectRoot, "datasets"));
    assert.match(sourcePath, /[0-9a-f]{32}\.parquet$/);

    const finalWoe = page.getByText("final-woe-iv", { exact: true }).last().locator("..");
    await finalWoe
      .locator("label")
      .filter({ hasText: "Purpose" })
      .locator("select")
      .selectOption("final");
    await finalWoe
      .locator("label")
      .filter({ hasText: "Smoothing" })
      .locator("input")
      .fill(
        JSON.stringify({
          method: "additive",
          alpha: 0.5,
          rationale:
            "The representative German Credit data contains sparse bins; additive smoothing stabilizes WOE.",
        }),
      );
    await saveStep(page, finalWoe, planVersion.plan_version_id);

    const metadata = page.getByText("define-metadata", { exact: true }).last().locator("..");
    await fillStepField(metadata, "Product", "term_loan");
    await fillStepField(metadata, "Segment", "retail");
    await fillStepField(metadata, "Observation Window", "2020 calendar year");
    await fillStepField(metadata, "Performance Window", "2021 calendar year");
    await metadata
      .locator("label")
      .filter({ hasText: "Reject Inference Position" })
      .locator("select")
      .selectOption("not_applied");
    await saveStep(page, metadata, planVersion.plan_version_id);

    const manualBinning = page.getByText("manual-binning", { exact: true }).last().locator("..");
    await manualBinning.getByLabel(/Accept automated bins/).check();
    await saveStep(page, manualBinning, planVersion.plan_version_id);

    const committed = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname.endsWith("/commit"),
    );
    await page.getByRole("button", { name: "Commit version", exact: true }).click();
    const commitResponse = await committed;
    assert.equal(commitResponse.status(), 200, await commitResponse.text());

    const runResponse = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        new URL(response.url()).pathname.endsWith("/runs"),
    );
    await page.getByRole("button", { name: "Run selected version" }).click();
    const runSubmission = await runResponse;
    assert.equal(runSubmission.status(), 201, await runSubmission.text());
    const runRecord = await runSubmission.json();
    await page.waitForFunction(() => document.body.innerText.includes("Status: succeeded"), null, {
      timeout: 120_000,
    });

    const run = await apiJson(
      apiBase + "/projects/" + project.project_id + "/runs/" + runRecord.run_id,
    );
    const runSteps = await apiJson(
      apiBase + "/projects/" + project.project_id + "/runs/" + runRecord.run_id + "/steps",
    );
    assert.equal(run.status, "succeeded");
    assert.equal(run.step_count, 31);
    assert.equal(runSteps.length, 31);
    assert.ok(runSteps.every((step) => step.status === "succeeded"));
    assert.equal((await stat(sourcePath)).isFile(), true);

    await downloadExport(page, "scorecard.csv", "text/csv");
    await downloadExport(page, "scorecard.py", "text/x-python");
    await downloadExport(page, "scorecard.sql", "application/sql");

    if (outputDir) {
      await mkdir(outputDir, { recursive: true });
      await page.getByText("Run Details", { exact: true }).scrollIntoViewIfNeeded();
      await page.screenshot({ path: join(outputDir, "dataset-browse-run.png"), fullPage: true });
    }

    console.log(
      JSON.stringify({
        ok: true,
        projectId: project.project_id,
        planId: plan.plan_id,
        planVersionId: planVersion.plan_version_id,
        runId: runRecord.run_id,
        fileName: "german_credit.parquet",
        stepCount: runSteps.length,
        invalidUploadRejected: true,
        cancellationPreservedSelection: true,
        sourceStoredUnderProject: true,
        scoringDownloadsVerified: ["scorecard.csv", "scorecard.py", "scorecard.sql"],
      }),
    );
  } catch (error) {
    for (const [name, logs] of processLogs) {
      console.error("--- " + name + " logs ---\n" + logs);
    }
    throw error;
  } finally {
    if (browser) await browser.close();
    await Promise.all(processes.map(stop));
    if (temporaryRoot) await rm(temporaryRoot, { recursive: true, force: true });
  }
}

await run();
