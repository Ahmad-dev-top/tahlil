/**
 * Browser smoke test against a running backend + frontend.
 *
 *   # terminal 1 (repo root): offline backend with simulated model latency
 *   LLM_MODE=fake SANDBOX_MODE=local DEMO_DELAY_S=0.4 uvicorn app.api:app --port 8000
 *   # terminal 2 (frontend/)
 *   npm run dev
 *   # terminal 3 (frontend/)  (first time: npm i -D playwright && npx playwright install chromium)
 *   npm run test:e2e
 *
 * Env: APP_URL (default http://localhost:3000), SHOTS_DIR (screenshots, default e2e/shots)
 */
const path = require("node:path");
const fs = require("node:fs");
const assert = require("node:assert/strict");
const { spawn, execFileSync } = require("node:child_process");
const { chromium } = require("playwright");

const APP_URL = process.env.APP_URL || "http://localhost:3000";
const API_URL = process.env.API_URL || "http://127.0.0.1:8000";
const SHOTS = process.env.SHOTS_DIR || path.join(__dirname, "shots");
const CSV = path.resolve(__dirname, "../../sample_data/sales.csv");
const ROOT = path.resolve(__dirname, "../..");

function pythonBin() {
  const candidates = [
    path.join(ROOT, ".venv", "Scripts", "python.exe"),
    path.join(ROOT, ".venv", "bin", "python"),
  ];
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) return candidate;
  }
  return process.platform === "win32" ? "python" : "python3";
}

function listenerPids() {
  if (process.platform === "win32") {
    const out = execFileSync(
      "powershell",
      [
        "-NoProfile",
        "-Command",
        "Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique",
      ],
      { encoding: "utf8" },
    );
    return out
      .split(/\s+/)
      .map((s) => s.trim())
      .filter((s) => /^\d+$/.test(s));
  }
  const out = execFileSync("ss", ["-ltnp", "sport = :8000"], { encoding: "utf8" });
  return [...new Set([...out.matchAll(/pid=(\d+)/g)].map((m) => m[1]))];
}

function stopBackend() {
  for (const pid of listenerPids()) {
    try {
      process.kill(Number(pid));
    } catch {
      /* already gone */
    }
  }
}

function startBackend() {
  const child = spawn(
    pythonBin(),
    [
      "-c",
      "from dotenv import load_dotenv; load_dotenv(); import uvicorn; uvicorn.run('app.api:app', host='127.0.0.1', port=8000)",
    ],
    {
      cwd: ROOT,
      env: { ...process.env, LLM_MODE: "fake", SANDBOX_MODE: "local", DEMO_DELAY_S: "0.4" },
      stdio: "ignore",
      windowsHide: true,
    },
  );
  return child;
}

async function waitHealth() {
  for (let i = 0; i < 40; i++) {
    try {
      const res = await fetch(`${API_URL}/health`);
      if (res.ok) return;
    } catch {
      /* server still down */
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error("backend did not come back");
}

(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1360, height: 900 } });
  const consoleErrors = [];
  page.on("console", (m) => {
    if (m.type() !== "error") return;
    const text = m.text();
    // The unreachable check stops the API on purpose, so the browser logs that refusal.
    if (text.includes("ERR_CONNECTION_REFUSED") || text.includes("Failed to fetch")) return;
    consoleErrors.push(text);
  });

  await page.goto(APP_URL);
  console.log("1. app loaded");

  // upload the sample CSV
  await page.getByTestId("csv-input").first().setInputFiles(CSV);
  await page.getByRole("heading", { name: "sales.csv" }).waitFor({ timeout: 15000 });
  console.log("2. CSV uploaded, dataset opened");
  await page.screenshot({ path: path.join(SHOTS, "1-welcome.png") });

  // ask via a suggestion chip and watch the step chips arrive one by one
  await page.getByRole("button", { name: "Which region brings in the most revenue?" }).click();
  const seen = new Set();
  const t0 = Date.now();
  while (Date.now() - t0 < 30000) {
    seen.add(await page.getByTestId("step").count());
    if (await page.getByTestId("answer").count()) break;
    await page.waitForTimeout(100);
  }
  await page.getByTestId("answer").waitFor({ timeout: 30000 });
  const counts = [...seen].sort((a, b) => a - b);
  console.log(`3. step counts observed while streaming: ${counts.join(", ")}`);
  assert.ok(counts.length >= 4, "steps should arrive incrementally (streaming), not all at once");

  await page.getByTestId("verified").waitFor();
  console.log("4. answer rendered with 'Numbers verified' badge");

  // open the data + SQL sections
  await page.getByRole("button", { name: /^Data · 20 rows/ }).click();
  await page.getByRole("button", { name: "SQL" }).click();
  assert.ok(await page.locator("table tbody tr").count() >= 20, "result table rows");
  assert.match(await page.locator("pre").first().innerText(), /SELECT \* FROM sales/);
  console.log("5. data table and SQL visible");
  await page.screenshot({ path: path.join(SHOTS, "2-answer.png"), fullPage: false });

  // follow-up in the same conversation
  await page.getByLabel("Question").fill("Now only for Punjab");
  await page.getByLabel("Question").press("Enter");
  await page.waitForFunction(() => document.querySelectorAll('[data-testid="answer"]').length === 2, null, {
    timeout: 30000,
  });
  assert.equal(await page.getByTestId("turn").count(), 2);
  // first question becomes the conversation title in the sidebar
  await page.locator("aside").getByText("Which region brings in the most revenue?").first().waitFor();
  console.log("6. follow-up answered; conversation titled in sidebar");

  // Stop mid-stream: the input must come back, and the turn is marked Stopped.
  await page.getByLabel("Question").fill("Show monthly revenue as a trend");
  await page.getByRole("button", { name: "Send" }).click();
  await page.getByTestId("turn").nth(2).getByTestId("step").first().waitFor({ timeout: 15000 });
  await page.getByRole("button", { name: "Stop" }).click();
  await page.getByTestId("stopped").waitFor({ timeout: 10000 });
  assert.equal(await page.getByLabel("Question").isDisabled(), false, "input should re-enable after Stop");
  console.log("7. Stop aborted the stream and re-enabled the input");
  await page.screenshot({ path: path.join(SHOTS, "5-stopped.png") });

  // Backend down: the app shows an unreachable state, then recovers on Retry.
  stopBackend();
  await page.reload();
  await page.getByTestId("api-unreachable").waitFor({ timeout: 15000 });
  await page.getByRole("heading", { name: "API unreachable" }).waitFor();
  console.log("8. API unreachable");
  await page.screenshot({ path: path.join(SHOTS, "6-unreachable.png") });
  const restarted = startBackend();
  restarted.unref();
  await waitHealth();
  await page.getByTestId("retry").click();
  await page.getByRole("heading", { name: "sales.csv" }).waitFor({ timeout: 15000 });
  console.log("9. Retry recovered the dataset");
  await page.screenshot({ path: path.join(SHOTS, "7-recovered.png") });

  // mobile layout: no horizontal overflow, drawer opens
  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(300);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  assert.ok(overflow <= 0, `page overflows horizontally by ${overflow}px on mobile`);
  await page.screenshot({ path: path.join(SHOTS, "3-mobile.png") });
  await page.getByRole("button", { name: "Open menu" }).click();
  await page.waitForTimeout(400);
  await page.screenshot({ path: path.join(SHOTS, "4-mobile-drawer.png") });
  console.log("10. mobile layout OK");

  assert.deepEqual(consoleErrors, [], `console errors: ${consoleErrors.join(" | ")}`);
  await browser.close();
  console.log(`\nE2E PASSED. Screenshots in ${SHOTS}`);
})().catch((e) => {
  console.error("E2E FAILED:", e);
  process.exit(1);
});
