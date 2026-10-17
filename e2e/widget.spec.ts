import { expect, test, type Page } from "@playwright/test";

// Locators pierce the widget's open shadow root.
const w = (page: Page) => page.locator("findaro-search");
const input = (page: Page) => w(page).locator("input[type=search]");
const chips = (page: Page) => w(page).locator(".chip");
const cards = (page: Page) => w(page).locator(".grid .card");
const composer = (page: Page) => w(page).locator(".composer textarea"); // AI mode

async function search(page: Page, q: string) {
  await input(page).fill(q);
  await input(page).press("Enter");
}

async function ask(page: Page, q: string) {
  const before = await w(page).locator(".msg.assistant").count();
  await composer(page).fill(q);
  await composer(page).press("Enter");
  // wait for this turn's answer to finish streaming
  await expect(w(page).locator(".msg.assistant")).toHaveCount(before + 1);
  await expect(w(page).locator(".msg.assistant .text").last()).not.toHaveClass(/typing/, { timeout: 20_000 });
}

test.beforeEach(async ({ page }) => {
  await page.goto("/demo.html");
  await expect(input(page)).toBeVisible();
});

test("search shows understood chips, pills and product cards", async ({ page }) => {
  await search(page, "kaale joote 1000 ke andar");
  await expect(chips(page).filter({ hasText: "Under ₹1,000" })).toBeVisible();
  await expect(chips(page).filter({ hasText: "Black" })).toBeVisible();
  await expect(cards(page).first()).toBeVisible();
  // selling price is the price element's first text node (the struck-through MRP is a child span)
  const prices = await w(page).locator(".grid .card .price").evaluateAll((els) =>
    els.map((el) => Number((el.firstChild?.textContent ?? "").replace(/[^\d.]/g, ""))));
  expect(prices.length).toBeGreaterThan(0);
  for (const p of prices) expect(p).toBeLessThanOrEqual(1000);
  await w(page).locator(".filters-toggle").click();
  await expect(w(page).locator(".pills .pill").first()).toBeVisible();
  await expect(w(page).locator("[role=status]")).toContainText(/\d+ results/);
});

test("removing a chip sends a patch and widens the results", async ({ page }) => {
  await search(page, "kaale joote 1000 ke andar");
  const status = w(page).locator("[role=status]");
  await expect(status).toContainText(/results/);
  const before = Number((await status.innerText()).match(/\d+/)![0]);
  const req = page.waitForRequest((r) => r.url().endsWith("/v1/search") && !!r.postDataJSON()?.patch?.length);
  await chips(page).filter({ hasText: "Black" }).getByRole("button").click();
  expect((await req).postDataJSON().patch).toEqual([{ op: "remove_filter", field: "color", value: "Black" }]);
  await expect(chips(page).filter({ hasText: "Black" })).toHaveCount(0);
  await expect(chips(page).filter({ hasText: "Under ₹1,000" })).toBeVisible();
  await expect.poll(async () => Number((await status.innerText()).match(/\d+/)?.[0] ?? 0)).toBeGreaterThan(before);
});

test("facet pill refines the results", async ({ page }) => {
  await search(page, "water bottle");
  await w(page).locator(".filters-toggle").click();
  const pill = w(page).locator(".pills .pill").first();
  await expect(pill).toBeVisible();
  const label = (await pill.evaluate((el) => el.firstChild?.textContent ?? "")).trim();
  await pill.click();
  await expect(chips(page).filter({ hasText: label })).toBeVisible();
});

test("ask AI: new search then refinement in chat", async ({ page }) => {
  await w(page).getByRole("radio", { name: /ask ai/i }).click();
  await ask(page, "water bottle");
  await expect(w(page).locator("[role=log]")).toBeVisible();
  await expect(cards(page).first()).toBeVisible();
  await ask(page, "only copper");
  await expect(chips(page).filter({ hasText: "Copper" })).toHaveCount(1);
  await expect(w(page).locator(".msg.user .text").last()).toHaveText("only copper");
  await expect(w(page).locator(".msg.assistant .text").last()).not.toBeEmpty();
});

test("clarifier chip: slightly over budget", async ({ page }) => {
  await w(page).getByRole("radio", { name: /ask ai/i }).click();
  await ask(page, "saree under 1000");
  const chip = w(page).locator("[data-clarify]", { hasText: "Show slightly over budget" });
  await expect(chip).toBeVisible();
  await expect(w(page).locator(".clarify p")).toContainText("₹1,000");
  await chip.click();
  await expect(chips(page).filter({ hasText: "Under ₹1,300" })).toBeVisible({ timeout: 20_000 });
  // never two questions in a row (one-click "next" refinements may follow)
  await expect(w(page).locator("[data-clarify]:not([data-clarify=next])")).toHaveCount(0);
});

test("ask AI: greeting offers category chips that search", async ({ page }) => {
  await w(page).getByRole("radio", { name: /ask ai/i }).click();
  await ask(page, "hi");
  const chip = w(page).locator("[data-clarify]", { hasText: "Footwear" });
  await expect(chip).toBeVisible();
  await chip.click();
  await expect(w(page).locator(".msg.user .text").last()).toHaveText("Footwear");
  await expect(cards(page).first()).toBeVisible({ timeout: 20_000 });
});

test("no-match state", async ({ page }) => {
  await search(page, "guitar strings");
  const empty = w(page).locator("[data-state=no-match]");
  await expect(empty).toBeVisible();
  await expect(empty).toContainText("guitar strings");
  await expect(cards(page)).toHaveCount(0);
});

test("keyboard: switch mode, search, escape clears", async ({ page }) => {
  await input(page).focus();
  await page.keyboard.type("pressure cooker");
  await page.keyboard.press("Enter");
  await expect(cards(page).first()).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(input(page)).toHaveValue("");
  await expect(cards(page)).toHaveCount(0);
  await w(page).getByRole("radio", { name: /ask ai/i }).focus();
  await page.keyboard.press("Enter");
  await expect(w(page).getByRole("radio", { name: /ask ai/i })).toHaveAttribute("aria-checked", "true");
  await expect(w(page).getByRole("search")).toBeVisible();
});

test("fits the viewport without horizontal scroll", async ({ page }) => {
  await search(page, "running shoes");
  await expect(cards(page).first()).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});

test("product drawer: ask about a product, then close", async ({ page }) => {
  await search(page, "women shoes under 1k");
  await w(page).locator(".ask").first().click();
  const drawer = w(page).locator(".drawer");
  await expect(drawer).toBeVisible();
  await expect(drawer.locator("#zd-title")).not.toBeEmpty();
  await expect(drawer.locator(".facts dt").first()).toBeVisible(); // every listed field is shown
  await drawer.locator(".suggestions .pill").first().click();
  await expect(drawer.locator(".msg.assistant .text").last()).not.toHaveClass(/typing/, { timeout: 60_000 });
  await expect(drawer.locator(".msg.assistant .text").last()).not.toBeEmpty();
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  await expect(w(page).locator(".ask").first()).toBeFocused(); // focus returns to the button that opened it
});
