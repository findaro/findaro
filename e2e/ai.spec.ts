import { expect, test, type Page } from "@playwright/test";

// AI Mode, full page (examples/plain-html/ai.html → ai-demo.html with the demo keys). Locators pierce the shadow root.
const w = (page: Page) => page.locator("findaro-search");
const composer = (page: Page) => w(page).locator(".composer textarea");
const cards = (page: Page) => w(page).locator(".tcards .pc");
const turns = (page: Page) => w(page).locator(".log .msg.assistant");

async function send(page: Page, q: string) {
  const before = await turns(page).count();
  await composer(page).fill(q);
  await composer(page).press("Enter");
  await settle(page, before + 1);
}

async function settle(page: Page, n: number) {
  await expect(turns(page)).toHaveCount(n);
  await expect(turns(page).last().locator(".text")).not.toHaveClass(/typing/, { timeout: 20_000 });
}

test.beforeEach(async ({ page }) => {
  await page.goto("/ai-demo.html");
  await expect(w(page).locator(".hello h2")).toBeVisible();
});

test("a query shows inline cards with the requirement line and next-step rows", async ({ page }) => {
  await expect(w(page).locator(".starters .nrow")).toHaveCount(4);
  await send(page, "black shoes under 1000");
  await expect(w(page).locator(".log .msg.user .text")).toHaveText("black shoes under 1000");
  await expect(cards(page).first()).toBeVisible();
  expect(await cards(page).count()).toBeLessThanOrEqual(6); // first 6, the rest behind "Show N more"
  await expect(cards(page).first().locator(".req")).toContainText(/Matches \d\/\d/);
  await expect(cards(page).first().locator(".act[data-ask]")).toBeVisible();
  await expect(w(page).locator(".how summary")).toContainText(/Searched in/);
  await w(page).locator(".how summary").click();
  await expect(w(page).locator(".how .uchip", { hasText: "Black" })).toBeVisible();
  await expect(w(page).locator("[role=log]")).toHaveAttribute("aria-live", "polite");
});

test("a next-step row refines the results in a new turn", async ({ page }) => {
  await send(page, "steel water bottle");
  const row = w(page).locator(".clarify .nrow[data-clarify=next]").first();
  await expect(row).toBeVisible();
  const label = (await row.locator("span").first().innerText()).trim();
  const req = page.waitForRequest((r) => r.url().endsWith("/v1/chat") && !!r.postDataJSON()?.patch?.length);
  await row.click();
  const body = (await req).postDataJSON();
  expect(body.message).toBe("");
  await settle(page, 2);
  await expect(w(page).locator(".log .msg.user .text").last()).toHaveText(label);
  await expect(turns(page).last().locator(".tcards .pc").first()).toBeVisible();
});

test("select two products and compare them", async ({ page }) => {
  await send(page, "steel water bottle");
  const boxes = w(page).locator(".pc .sel input");
  await boxes.nth(0).check();
  await boxes.nth(1).check();
  const bar = w(page).locator(".selbar");
  await expect(bar).toContainText("2 selected");
  const req = page.waitForRequest((r) => r.url().endsWith("/v1/chat") && r.postDataJSON()?.product_ids?.length === 2);
  await bar.getByRole("button", { name: "Compare" }).click();
  expect((await req).postDataJSON().message).toBe("Compare these");
  await settle(page, 2);
  const table = turns(page).last().locator(".cmp");
  await expect(table).toBeVisible();
  await expect(table.locator("thead th")).toHaveCount(2);
  await expect(table.locator("tbody th", { hasText: "Price" })).toBeVisible();
  // at most 3 at once (the API's limit): a 4th selection is refused with a notice
  await boxes.nth(2).check();
  await boxes.nth(3).click();
  await expect(boxes.nth(3)).not.toBeChecked();
  await expect(w(page).locator(".notice")).toBeVisible();
});

test("conversations are kept: reload, reopen from the sidebar, delete", async ({ page }) => {
  await send(page, "steel water bottle");
  await page.reload();
  const conv = w(page).locator(".side .conv", { hasText: "steel water bottle" });
  await expect(conv).toBeVisible();
  await conv.click();
  await expect(cards(page).first()).toBeVisible();
  await expect(w(page).locator(".log .msg.user .text").first()).toHaveText("steel water bottle");
  await w(page).locator(".side .ci .del").first().click();
  await w(page).locator(".side [data-confirm]").click();
  await expect(w(page).locator(".side .conv")).toHaveCount(0);
  await expect(w(page).locator(".hello h2")).toBeVisible();
});

test("phone: the sidebar is a drawer; Escape closes it", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const menu = w(page).getByRole("button", { name: "Open chat history" });
  await expect(menu).toBeVisible();
  await expect(w(page).locator(".side")).toBeHidden();
  await menu.click();
  await expect(w(page).locator(".side")).toBeVisible();
  await expect(menu).toHaveAttribute("aria-expanded", "true");
  await page.keyboard.press("Escape");
  await expect(w(page).locator(".side")).toBeHidden();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});
