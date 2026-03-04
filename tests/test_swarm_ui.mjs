/**
 * Playwright browser tests for the Clawllama Swarm Dashboard.
 *
 * Run:  npx playwright test tests/test_swarm_ui.mjs --reporter=list
 *
 * Requires the swarm server running on localhost:8765.
 */
import { test, expect } from "@playwright/test";

const BASE = "http://localhost:8765";

test.describe("Swarm Dashboard", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(`${BASE}/swarm`);
  });

  // ── Layout & Branding ──────────────────────────────────────────────

  test("page title is Clawllama", async ({ page }) => {
    await expect(page).toHaveTitle("Clawllama Swarm Control");
  });

  test("header shows Clawllama Swarm Control", async ({ page }) => {
    const h1 = page.locator("header h1");
    await expect(h1).toHaveText("Clawllama Swarm Control");
  });

  test("header has neon cyan color", async ({ page }) => {
    const h1 = page.locator("header h1");
    const color = await h1.evaluate((el) => getComputedStyle(el).color);
    // --neon-cyan: #00fff5 → rgb(0, 255, 245)
    expect(color).toBe("rgb(0, 255, 245)");
  });

  test("status indicator is visible", async ({ page }) => {
    const statusDot = page.locator("#status-dot");
    await expect(statusDot).toBeVisible();
  });

  test("workers counter is visible", async ({ page }) => {
    const workers = page.locator("#worker-count");
    await expect(workers).toBeVisible();
  });

  test("tick counter is visible", async ({ page }) => {
    const tick = page.locator("#tick-counter");
    await expect(tick).toBeVisible();
  });

  // ── Event Log ──────────────────────────────────────────────────────

  test("event log shows initialisation message", async ({ page }) => {
    const log = page.locator("#event-log");
    await expect(log).toContainText("Swarm Control UI initialised");
  });

  // ── WebSocket ──────────────────────────────────────────────────────

  test("WebSocket connects and status turns green", async ({ page }) => {
    // Wait for the WebSocket connected log entry
    const log = page.locator("#event-log");
    await expect(log).toContainText("WebSocket connected", { timeout: 5000 });

    // Status dot should have 'connected' class
    const dot = page.locator("#status-dot");
    await expect(dot).toHaveClass(/connected/);
  });

  test("status text shows Connected", async ({ page }) => {
    await page.waitForTimeout(1000);
    const text = page.locator("#status-text");
    await expect(text).toHaveText("Connected");
  });

  // ── Canvas layers ──────────────────────────────────────────────────

  test("hex background canvas exists", async ({ page }) => {
    const canvas = page.locator("#canvas-hex");
    await expect(canvas).toBeAttached();
  });

  test("particle canvas exists", async ({ page }) => {
    const canvas = page.locator("#canvas-particles");
    await expect(canvas).toBeAttached();
  });

  // ── Terminal grid container ────────────────────────────────────────

  test("terminal grid container exists", async ({ page }) => {
    const grid = page.locator("#terminal-grid");
    await expect(grid).toBeVisible();
  });

  // ── Responsive: viewport resize ────────────────────────────────────

  test("dashboard renders at mobile width", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    const header = page.locator("header");
    await expect(header).toBeVisible();
    const log = page.locator("#event-log");
    await expect(log).toBeVisible();
  });

  test("dashboard renders at 4K width", async ({ page }) => {
    await page.setViewportSize({ width: 3840, height: 2160 });
    const header = page.locator("header");
    await expect(header).toBeVisible();
    const grid = page.locator("#terminal-grid");
    await expect(grid).toBeVisible();
  });

  // ── No console errors ──────────────────────────────────────────────

  test("no JavaScript errors on load", async ({ page }) => {
    const errors = [];
    page.on("pageerror", (err) => errors.push(err.message));
    await page.goto(`${BASE}/swarm`);
    await page.waitForTimeout(2000);
    expect(errors).toEqual([]);
  });

  // ── Screenshot: visual sanity ──────────────────────────────────────

  test("visual snapshot", async ({ page }) => {
    await page.waitForTimeout(1500); // let animations settle
    await page.screenshot({ path: "/tmp/clawllama-swarm-test.png", fullPage: true });
  });
});

test.describe("Single Agent Page", () => {
  test("single agent page loads", async ({ page }) => {
    await page.goto(`${BASE}/`);
    await expect(page).toHaveTitle("Clawllama");
  });

  test("single agent header shows Clawllama", async ({ page }) => {
    await page.goto(`${BASE}/`);
    const h1 = page.locator("header h1");
    await expect(h1).toHaveText("Clawllama");
  });
});
