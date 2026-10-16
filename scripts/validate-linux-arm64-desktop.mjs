import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createServer } from "node:net";
import { homedir, tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createHash } from "node:crypto";
import {
  access,
  copyFile,
  mkdir,
  mkdtemp,
  readFile,
  rename,
  rm,
  symlink,
  writeFile,
} from "node:fs/promises";
import { promisify } from "node:util";
import { execFile as execFileCallback } from "node:child_process";

const execFile = promisify(execFileCallback);
const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const appBinary = process.env.CARDRE_APP_BINARY ?? "/usr/bin/cardre";
const sidecarBinary =
  process.env.CARDRE_SIDECAR_BINARY ?? "/usr/bin/cardre-api";
const webKitDriver = process.env.WEBKIT_WEBDRIVER ?? "/usr/bin/WebKitWebDriver";
const tauriDriver =
  process.env.TAURI_DRIVER ?? join(homedir(), ".cargo", "bin", "tauri-driver");
const datasetPath =
  process.env.CARDRE_GERMAN_CREDIT_DATASET ??
  join(repositoryRoot, "datasets", "german_credit", "german_credit.parquet");
const outputDirectory =
  process.env.CARDRE_VALIDATION_OUTPUT ??
  join(
    repositoryRoot,
    "docs",
    "release",
    "validation",
    "linux-arm64-2026-10-16",
    "artifacts",
  );
const noDevelopmentPath = "/usr/sbin:/sbin";
const processes = [];
const driverLogs = [];
let driver;
let driverUrl;
let sessionId;
let appPid;
let stateRoot;
let appHome;
let downloadDirectory;
let registryPath;

function delay(ms) {
  return new Promise((resolveDelay) => setTimeout(resolveDelay, ms));
}

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

async function waitFor(description, predicate, timeoutMs = 20_000) {
  const deadline = Date.now() + timeoutMs;
  let lastError;
  while (Date.now() < deadline) {
    try {
      const result = await predicate();
      if (result) return result;
    } catch (error) {
      lastError = error;
    }
    await delay(200);
  }
  throw new Error(
    `Timed out waiting for ${description}${lastError ? `: ${lastError.message}` : ""}`,
  );
}

function childEnvironment() {
  return {
    ...process.env,
    HOME: appHome,
    XDG_CONFIG_HOME: join(appHome, ".config"),
    XDG_DATA_HOME: join(appHome, ".local", "share"),
    XDG_CACHE_HOME: join(appHome, ".cache"),
    XDG_DOWNLOAD_DIR: downloadDirectory,
    CARDRE_REGISTRY_PATH: registryPath,
    PATH: noDevelopmentPath,
  };
}

async function startDriver() {
  const port = await freePort();
  const nativePort = await freePort();
  driverUrl = `http://127.0.0.1:${port}`;
  driver = spawn(
    tauriDriver,
    [
      "--port",
      String(port),
      "--native-port",
      String(nativePort),
      "--native-driver",
      webKitDriver,
    ],
    { env: childEnvironment(), stdio: ["ignore", "pipe", "pipe"] },
  );
  processes.push(driver);
  for (const stream of [driver.stdout, driver.stderr]) {
    stream.setEncoding("utf8");
    stream.on("data", (chunk) => driverLogs.push(chunk));
  }
  await waitFor("tauri-driver readiness", async () => {
    if (driver.exitCode !== null)
      throw new Error(`tauri-driver exited with ${driver.exitCode}`);
    const response = await fetch(`${driverUrl}/status`);
    return response.ok;
  });
}

async function webdriver(method, path, body) {
  const response = await fetch(`${driverUrl}${path}`, {
    method,
    headers: body ? { "content-type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
    signal: AbortSignal.timeout(45_000),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || payload.value?.error) {
    throw new Error(
      `${method} ${path} returned ${response.status}: ${JSON.stringify(payload.value ?? payload)}`,
    );
  }
  return payload.value;
}

async function startSession() {
  const value = await webdriver("POST", "/session", {
    capabilities: {
      alwaysMatch: {
        "tauri:options": { application: appBinary, args: [] },
      },
    },
  });
  sessionId = value.sessionId;
  appPid = await execFile("/usr/bin/pgrep", ["-n", "-f", "^/usr/bin/cardre$"])
    .then(({ stdout }) => Number(stdout.trim()))
    .catch(() => undefined);
  await webdriver("POST", `/session/${sessionId}/timeouts`, {
    implicit: 2_000,
    pageLoad: 30_000,
    script: 30_000,
  });
  await waitFor("Cardre webview to load", async () => {
    return (
      (await script(
        "return document.readyState === 'complete' && !!document.body",
      )) === true
    );
  });
  return sessionId;
}

async function endSession() {
  if (!sessionId) return;
  const appWindowId = await execFile("/usr/bin/xdotool", [
    "search",
    "--onlyvisible",
    "--name",
    "^Cardre$",
  ])
    .then(({ stdout }) => stdout.trim().split("\n")[0])
    .catch(() => "");
  if (appWindowId) {
    await execFile("/usr/bin/xdotool", [
      "key",
      "--window",
      appWindowId,
      "--clearmodifiers",
      "alt+F4",
    ]).catch(() => {});
  }
  if (appPid) {
    const processExited = async () => {
      try {
        const stat = await readFile(`/proc/${appPid}/stat`, "utf8");
        return stat.split(" ")[2] === "Z" ? true : false;
      } catch {
        return true;
      }
    };
    const closedGracefully = await waitFor(
      "Cardre app to close",
      processExited,
      8_000,
    )
      .then(() => true)
      .catch(() => false);
    if (!closedGracefully && appWindowId) {
      await execFile("/usr/bin/xdotool", ["windowclose", appWindowId]).catch(
        () => {},
      );
      await waitFor("Cardre app window to close", processExited, 8_000).catch(
        () => {},
      );
    }
  }
  await webdriver("DELETE", `/session/${sessionId}`).catch(() => {});
  sessionId = undefined;
  appPid = undefined;
}

async function findElement(selector, using = "css selector") {
  const value = await webdriver("POST", `/session/${sessionId}/element`, {
    using,
    value: selector,
  });
  const id = value["element-6066-11e4-a52e-4f735466cecf"];
  assert.ok(id, `WebDriver did not return an element for ${selector}`);
  return id;
}

async function click(selector, using = "css selector") {
  const id = await findElement(selector, using);
  await webdriver("POST", `/session/${sessionId}/element/${id}/click`, {});
}

async function chooseFile(selector, path) {
  const id = await findElement(selector);
  await webdriver("POST", `/session/${sessionId}/element/${id}/value`, {
    text: path,
    value: Array.from(path),
  });
}

async function fill(selector, text, using = "css selector") {
  const id = await findElement(selector, using);
  await webdriver("POST", `/session/${sessionId}/element/${id}/clear`, {});
  await webdriver("POST", `/session/${sessionId}/element/${id}/value`, {
    text,
    value: Array.from(text),
  });
}

async function typeInto(selector, text, using = "css selector") {
  const id = await findElement(selector, using);
  await webdriver("POST", `/session/${sessionId}/element/${id}/value`, {
    text,
    value: Array.from(text),
  });
}

async function script(source, args = []) {
  return webdriver("POST", `/session/${sessionId}/execute/sync`, {
    script: source,
    args,
  });
}

async function bodyText() {
  return script("return document.body.innerText");
}

async function waitForText(text, timeoutMs = 20_000) {
  return waitFor(
    `page text ${JSON.stringify(text)}`,
    async () => {
      const content = await bodyText();
      return content.includes(text) ? content : false;
    },
    timeoutMs,
  );
}

async function apiJson(path, init) {
  const response = await fetch(`${await apiBase()}${path}`, init);
  const body = await response.json();
  assert.ok(
    response.ok,
    `${init?.method ?? "GET"} ${path} returned ${response.status}: ${JSON.stringify(body)}`,
  );
  return body;
}

async function apiBase() {
  return waitFor("injected local API URL", async () => {
    const value = await script("return window.__API_URL__ || null");
    return typeof value === "string" ? value : false;
  });
}

function elementPathForLabel(stepId, labelText, tag = "input") {
  const card = `//div[div[normalize-space(.)='${stepId}']]`;
  return `(${card})//label[.//span[starts-with(normalize-space(.),'${labelText}')]]//${tag}`;
}

async function setSelectOption(stepId, labelText, value) {
  const card = `//div[div[normalize-space(.)='${stepId}']]`;
  const optionPath = `(${card})//label[.//span[starts-with(normalize-space(.),'${labelText}')]]//option[@value='${value}']`;
  await click(optionPath, "xpath");
}

async function nativeDialogs() {
  const ids = await execFile("/usr/bin/xdotool", [
    "search",
    "--onlyvisible",
    "--name",
    ".",
  ])
    .then(({ stdout }) => stdout.trim().split("\n").filter(Boolean))
    .catch(() => []);
  const windows = [];
  for (const id of ids) {
    const title = await execFile("/usr/bin/xdotool", ["getwindowname", id])
      .then(({ stdout }) => stdout.trim())
      .catch(() => "");
    if (title && title !== "Cardre") windows.push({ id, title });
  }
  return windows;
}

async function clickNativeKey(key, windowId) {
  await execFile("/usr/bin/xdotool", [
    "key",
    "--window",
    windowId,
    "--clearmodifiers",
    key,
  ]);
}

async function typeNativeText(text, windowId) {
  await execFile("/usr/bin/xdotool", [
    "type",
    "--window",
    windowId,
    "--clearmodifiers",
    "--delay",
    "1",
    text,
  ]);
}

async function saveFileDialogTo(path, windowId) {
  await clickNativeKey("ctrl+l", windowId);
  await typeNativeText(path, windowId);
  await clickNativeKey("Return", windowId);
  await delay(300);
  await clickNativeKey("Return", windowId);
}

async function selectDatasetThroughFileInput() {
  await chooseFile("input[aria-label='Browse for Parquet file']", datasetPath);
  await waitForText("Ready: german_credit.parquet", 30_000);
}

async function waitForDownload(fileName, timeoutMs = 15_000) {
  const path = join(downloadDirectory, fileName);
  await waitFor(
    `download ${fileName}`,
    async () => {
      try {
        await access(path);
        return path;
      } catch {
        return false;
      }
    },
    timeoutMs,
  );
  return path;
}

async function clickDownload(buttonSelector, fileName, using = "css selector") {
  const clickPromise = click(buttonSelector, using);
  clickPromise.catch(() => {});
  const path = join(downloadDirectory, fileName);
  const outcome = await waitFor(
    `download ${fileName} or its native save dialog`,
    async () => {
      try {
        await access(path);
        return "downloaded";
      } catch {
        const dialog = (await nativeDialogs())[0];
        if (dialog) return dialog;
        return false;
      }
    },
    20_000,
  );
  if (outcome !== "downloaded") {
    await saveFileDialogTo(path, outcome.id);
  }
  await clickPromise;
  await waitForDownload(fileName);
  const content = await readFile(path);
  assert.ok(content.length > 0, `${fileName} download is empty`);
  return path;
}

async function screenshot(name) {
  const value = await webdriver("GET", `/session/${sessionId}/screenshot`);
  await writeFile(join(outputDirectory, name), Buffer.from(value, "base64"));
}

async function validateAuditChecksums(path) {
  const { stdout } = await execFile("/usr/bin/unzip", [
    "-p",
    path,
    "checksums.sha256",
  ]);
  const entries = stdout
    .trim()
    .split("\n")
    .filter(Boolean)
    .map((line) => {
      const separator = line.indexOf("  ");
      assert.ok(separator > 0, `Malformed checksum entry: ${line}`);
      return [line.slice(0, separator), line.slice(separator + 2)];
    });
  assert.ok(entries.length > 0, "Audit pack checksum list is empty");
  for (const [expected, member] of entries) {
    const { stdout: bytes } = await execFile(
      "/usr/bin/unzip",
      ["-p", path, member],
      {
        encoding: null,
        maxBuffer: 64 * 1024 * 1024,
      },
    );
    const actual = createHash("sha256").update(bytes).digest("hex");
    assert.equal(
      actual,
      expected,
      `Audit pack checksum mismatch for ${member}`,
    );
  }
  return entries.length;
}

async function readDriverLogs() {
  await writeFile(
    join(outputDirectory, "tauri-driver.log"),
    driverLogs.join(""),
  );
}

async function runWorkflow() {
  const apiUrl = await apiBase();
  console.log("Desktop app loaded; local API is reachable.");
  await waitForText("Evidence-first scorecard workflows.");
  await fill(
    "input[placeholder='/home/me/example.cardre']",
    join(stateRoot, "project.cardre"),
  );
  await fill("input[placeholder='My Scorecard']", "German Credit ARM64");
  await click("//button[normalize-space(.)='Create Project']", "xpath");

  const projects = await waitFor("created project registration", async () => {
    const response = await fetch(`${apiUrl}/projects`);
    if (!response.ok) return false;
    const body = await response.json();
    return (
      body.projects.find((item) => item.name === "German Credit ARM64") ?? false
    );
  });
  const projectId = projects.project_id;
  console.log(`Created isolated project ${projectId}.`);

  await fill("input[placeholder='New plan name']", "German Credit");
  await click("//button[normalize-space(.)='Create plan']", "xpath");
  const plans = await apiJson(`/projects/${projectId}/plans`);
  const plan = await waitFor("created plan", async () => {
    const value = await apiJson(`/projects/${projectId}/plans`);
    return value.plans.find((item) => item.name === "German Credit") ?? false;
  });
  assert.ok(plan.plan_id, JSON.stringify(plans));
  console.log(`Created plan ${plan.plan_id}.`);

  await selectDatasetThroughFileInput();
  console.log("Imported German Credit through the desktop file input.");

  await fill(
    "//label[.//span[normalize-space(.)='Target column']]//input",
    "class",
    "xpath",
  );
  await fill("input[placeholder='good']", "good");
  await fill("input[placeholder='bad']", "bad");
  await click(
    "//button[normalize-space(.)='Generate launch pathway']",
    "xpath",
  );

  const planVersion = await waitFor(
    "draft PlanVersion",
    async () => {
      const result = await apiJson(
        `/projects/${projectId}/plans/${plan.plan_id}/versions`,
      );
      return result.versions.find((item) => !item.is_committed) ?? false;
    },
    30_000,
  );
  const versionStepsUrl = `/projects/${projectId}/plan-versions/${planVersion.plan_version_id}/steps`;
  const initialSteps = await apiJson(versionStepsUrl);
  const datasetStep = initialSteps[0];
  assert.ok(datasetStep, "Generated version is missing its load-data step");
  const projectRoot = join(stateRoot, "project.cardre");
  assert.ok(
    datasetStep.params.source_path.startsWith(join(projectRoot, "datasets")),
  );

  const woeCard = "//div[div[normalize-space(.)='final-woe-iv']]";
  await setSelectOption("final-woe-iv", "Purpose", "final");
  await fill(
    await elementPathForLabel("final-woe-iv", "Smoothing"),
    JSON.stringify({
      method: "additive",
      alpha: 0.5,
      rationale:
        "The representative German Credit data contains sparse bins; additive smoothing stabilizes WOE.",
    }),
    "xpath",
  );
  await click(`(${woeCard})//button[normalize-space(.)='Save']`, "xpath");
  await waitFor("final WOE choices to save", async () => {
    const steps = await apiJson(versionStepsUrl);
    const step = steps.find(
      (item) => item.canonical_step_id === "final-woe-iv",
    );
    return (
      step?.params?.purpose === "final" &&
      step?.params?.smoothing?.alpha === 0.5
    );
  });

  const metadataCard = "//div[div[normalize-space(.)='define-metadata']]";
  for (const [field, value] of [
    ["Product", "term_loan"],
    ["Segment", "retail"],
    ["Observation Window", "2020 calendar year"],
    ["Performance Window", "2021 calendar year"],
  ]) {
    await fill(
      await elementPathForLabel("define-metadata", field),
      value,
      "xpath",
    );
  }
  await setSelectOption(
    "define-metadata",
    "Reject Inference Position",
    "not_applied",
  );
  await click(`(${metadataCard})//button[normalize-space(.)='Save']`, "xpath");
  await waitFor("metadata choices to save", async () => {
    const steps = await apiJson(versionStepsUrl);
    const step = steps.find(
      (item) => item.canonical_step_id === "define-metadata",
    );
    return (
      step?.params?.product === "term_loan" &&
      step?.params?.reject_inference_position === "not_applied"
    );
  });

  const binningCard = "//div[div[normalize-space(.)='manual-binning']]";
  await click(
    `(${binningCard})//label[.//span[contains(normalize-space(.),'Accept automated bins')]]//input[@type='checkbox']`,
    "xpath",
  );
  await click(`(${binningCard})//button[normalize-space(.)='Save']`, "xpath");
  await waitFor("binning choice to save", async () => {
    const steps = await apiJson(versionStepsUrl);
    const step = steps.find(
      (item) => item.canonical_step_id === "manual-binning",
    );
    return step?.params?.accept_automated === true;
  });
  console.log("Saved explicit modeling decisions.");

  await click("//button[normalize-space(.)='Commit version']", "xpath");
  const committedVersion = await waitFor(
    "PlanVersion commit",
    async () => {
      const version = await apiJson(
        `/projects/${projectId}/plan-versions/${planVersion.plan_version_id}`,
      );
      return version.is_committed ? version : false;
    },
    30_000,
  );
  assert.equal(committedVersion.is_committed, true);

  await click("//button[normalize-space(.)='Run selected version']", "xpath");
  const run = await waitFor(
    "31-step run success",
    async () => {
      const response = await fetch(`${apiUrl}/projects/${projectId}/runs`);
      if (!response.ok) return false;
      const body = await response.json();
      const candidate = body.runs?.[0];
      if (candidate?.status === "failed") {
        throw new Error(
          `Run ${candidate.run_id} failed: ${JSON.stringify(candidate)}`,
        );
      }
      return candidate?.status === "succeeded" ? candidate : false;
    },
    180_000,
  );
  assert.equal(run.plan_version_id, planVersion.plan_version_id);
  assert.equal(run.step_count, 31);
  const runSteps = await apiJson(
    `/projects/${projectId}/runs/${run.run_id}/steps`,
  );
  assert.equal(runSteps.length, 31);
  assert.ok(runSteps.every((step) => step.status === "succeeded"));
  await waitForText("Status: succeeded", 180_000);
  console.log(`Run ${run.run_id} succeeded with all 31 steps.`);
  await screenshot("run-succeeded.png");

  const csvPath = await clickDownload(
    "button[aria-label='Download scorecard.csv']",
    "scorecard.csv",
  );
  const pythonPath = await clickDownload(
    "button[aria-label='Download scorecard.py']",
    "scorecard.py",
  );
  const sqlPath = await clickDownload(
    "button[aria-label='Download scorecard.sql']",
    "scorecard.sql",
  );
  assert.match(
    await readFile(pythonPath, "utf8"),
    /^"""Standalone scorecard scorer/m,
  );
  assert.match(
    await readFile(sqlPath, "utf8"),
    /^-- Standalone scorecard SQL/m,
  );
  assert.match(
    await readFile(csvPath, "utf8"),
    /^variable,bin_id,label,woe,coefficient,points/m,
  );

  await click("//button[normalize-space(.)='Generate report']", "xpath");
  const report = await waitFor("generated report", async () => {
    const response = await fetch(
      `${apiUrl}/projects/${projectId}/runs/${run.run_id}/reports`,
    );
    if (!response.ok) return false;
    const body = await response.json();
    return body.reports?.find((item) => item.report_type === "report") ?? false;
  });
  const handlesBeforeReport = await webdriver(
    "GET",
    `/session/${sessionId}/window/handles`,
  );
  await click("//button[normalize-space(.)='Open']", "xpath");
  const reportOpenStatus = await waitFor("report open result", async () => {
    const text = await bodyText();
    return text.includes("Report opened.") ||
      text.includes("Could not open report:")
      ? text
      : false;
  });
  assert.ok(reportOpenStatus.includes("Report opened."), reportOpenStatus);
  const handlesAfterReport = await webdriver(
    "GET",
    `/session/${sessionId}/window/handles`,
  );
  let reportOpened = false;
  let reportHtmlVerified = false;
  if (handlesAfterReport.length > handlesBeforeReport.length) {
    const reportHandle = handlesAfterReport.find(
      (handle) => !handlesBeforeReport.includes(handle),
    );
    await webdriver("POST", `/session/${sessionId}/window`, {
      handle: reportHandle,
    });
    await waitFor("report contents", async () => {
      const text = await bodyText();
      return (
        text.includes("Executive Summary") && text.includes("Reproducibility")
      );
    });
    await screenshot("report-open.png");
    await webdriver("DELETE", `/session/${sessionId}/window`);
    await webdriver("POST", `/session/${sessionId}/window`, {
      handle: handlesBeforeReport[0],
    });
    reportOpened = true;
    reportHtmlVerified = true;
  } else {
    const html = await script(
      "return document.querySelector('iframe[title=\"Model development report content\"]')?.srcdoc ?? null",
    );
    assert.equal(
      typeof html,
      "string",
      "A blocked popup should show the in-app report preview",
    );
    assert.match(html, /Executive Summary/);
    assert.match(html, /Reproducibility/);
    assert.equal(
      await script(
        "return document.querySelector('iframe[title=\"Model development report content\"]')?.getAttribute('sandbox') ?? null",
      ),
      "",
    );
    await screenshot("report-open.png");
    await click("//button[normalize-space(.)='Close report preview']", "xpath");
    reportOpened = true;
    reportHtmlVerified = true;
    console.log(
      "WebKit blocked the popup; displayed the report in a sandboxed in-app preview.",
    );
  }

  const reportPath = await clickDownload(
    "//button[normalize-space(.)='Download']",
    "model-development-report.html",
    "xpath",
  );
  assert.match(await readFile(reportPath, "utf8"), /Executive Summary/);

  await click("//button[normalize-space(.)='Generate audit pack']", "xpath");
  const auditPack = await waitFor("generated audit pack", async () => {
    const response = await fetch(
      `${apiUrl}/projects/${projectId}/exports?run_id=${run.run_id}`,
    );
    if (!response.ok) return false;
    const body = await response.json();
    return (
      body.exports?.find((item) => item.export_type === "audit_pack") ?? false
    );
  });
  assert.equal(auditPack.partial, false);
  const auditPath = await clickDownload(
    `button[aria-label='Download ${auditPack.file_name}']`,
    auditPack.file_name,
  );
  const verifiedChecksumCount = await validateAuditChecksums(auditPath);
  console.log(
    `Saved all exports and verified ${verifiedChecksumCount} audit checksums.`,
  );
  const committedDownloads = join(outputDirectory, "downloads");
  await mkdir(committedDownloads, { recursive: true });
  const savedDownloads = [];
  for (const source of [csvPath, pythonPath, sqlPath, reportPath, auditPath]) {
    const fileName = basename(source);
    const target = join(committedDownloads, fileName);
    await copyFile(source, target);
    savedDownloads.push(fileName);
  }

  await writeFile(
    join(outputDirectory, "desktop-workflow-result.json"),
    `${JSON.stringify(
      {
        ok: true,
        architecture: "arm64",
        os: "Ubuntu 24.04",
        appBinary,
        sidecarResolvedBesideApp: true,
        developmentPath: noDevelopmentPath,
        projectId,
        planId: plan.plan_id,
        planVersionId: planVersion.plan_version_id,
        planVersionCommitted: true,
        runId: run.run_id,
        stepCount: runSteps.length,
        allStepsSucceeded: runSteps.every(
          (step) => step.status === "succeeded",
        ),
        datasetSelectedThroughFileInput: true,
        selectedDownloadDirectory: downloadDirectory,
        downloads: savedDownloads,
        reportOpened,
        reportHtmlVerified,
        auditPackChecksumsVerified: verifiedChecksumCount,
      },
      null,
      2,
    )}\n`,
  );

  return {
    projectId,
    planId: plan.plan_id,
    planVersionId: planVersion.plan_version_id,
    runId: run.run_id,
    reportId: report.report_id,
    auditExportId: auditPack.export_id,
    verifiedChecksumCount,
    downloads: savedDownloads,
    datasetSelectedThroughFileInput: true,
    reportOpened,
    reportHtmlVerified,
  };
}

async function verifyReopenState(expected) {
  await endSession();
  await startSession();
  await waitForText("German Credit ARM64");
  const projects = await apiJson("/projects");
  assert.ok(
    projects.projects.some(
      (project) => project.project_id === expected.projectId,
    ),
  );
  await click(
    "//button[.//div[normalize-space(.)='German Credit ARM64']]",
    "xpath",
  );
  const version = await apiJson(
    `/projects/${expected.projectId}/plan-versions/${expected.planVersionId}`,
  );
  const run = await apiJson(
    `/projects/${expected.projectId}/runs/${expected.runId}`,
  );
  assert.equal(version.is_committed, true);
  assert.equal(run.status, "succeeded");
  await waitForText("Status: succeeded");
  await screenshot("reopened-project.png");
  console.log(
    "Reopened the app; project, committed version, and succeeded run persisted.",
  );
  return {
    projectPersisted: true,
    planVersionPersisted: true,
    succeededRunPersisted: true,
  };
}

async function verifyUnavailableSidecar() {
  await endSession();
  const disabledPath = `${sidecarBinary}.validation-disabled`;
  await access(sidecarBinary);
  await rename(sidecarBinary, disabledPath);
  try {
    await startSession();
    await waitForText("Cardre could not start its local API", 20_000);
    const text = await bodyText();
    assert.match(text, /Could not resolve sidecar/);
    await screenshot("sidecar-unavailable.png");
    console.log("A missing sidecar produces a visible startup error.");
    return { unavailableSidecarShowsClearError: true };
  } finally {
    await endSession();
    await rename(disabledPath, sidecarBinary);
  }
}

async function stopDriver() {
  if (!driver || driver.exitCode !== null) return;
  const exited = new Promise((resolveExit) => driver.once("exit", resolveExit));
  driver.kill("SIGTERM");
  await Promise.race([exited, delay(5_000)]);
  if (driver.exitCode === null) driver.kill("SIGKILL");
}

async function main() {
  assert.ok(
    (await readFile(datasetPath)).length > 0,
    `Missing fixture: ${datasetPath}`,
  );
  await mkdir(outputDirectory, { recursive: true });
  stateRoot = await mkdtemp(join(tmpdir(), "cardre-linux-arm64-desktop-"));
  appHome = join(stateRoot, "home");
  downloadDirectory = join(stateRoot, "chosen-downloads");
  registryPath = join(stateRoot, "registry", "projects.json");
  await mkdir(join(appHome, ".config"), { recursive: true });
  await mkdir(downloadDirectory, { recursive: true });
  await mkdir(dirname(registryPath), { recursive: true });
  await writeFile(
    join(appHome, ".config", "user-dirs.dirs"),
    `XDG_DOWNLOAD_DIR="${downloadDirectory}"\n`,
  );
  await symlink(downloadDirectory, join(appHome, "Downloads"));

  await startDriver();
  await startSession();
  const workflow = await runWorkflow();
  const persistence = await verifyReopenState(workflow);
  const sidecarFailure = await verifyUnavailableSidecar();
  await writeFile(
    join(outputDirectory, "desktop-workflow-result.json"),
    `${JSON.stringify({ ok: true, ...workflow, ...persistence, ...sidecarFailure }, null, 2)}\n`,
  );
  console.log(
    JSON.stringify({
      ok: true,
      ...workflow,
      ...persistence,
      ...sidecarFailure,
    }),
  );
}

try {
  await main();
} catch (error) {
  console.error(error);
  if (sessionId) {
    await bodyText()
      .then((text) => console.error("--- visible page text ---\n" + text))
      .catch(() => {});
    await screenshot("failure.png").catch(() => {});
  }
  console.error(driverLogs.join(""));
  process.exitCode = 1;
} finally {
  await endSession();
  await stopDriver();
  await readDriverLogs().catch(() => {});
  if (stateRoot) await rm(stateRoot, { recursive: true, force: true });
}
