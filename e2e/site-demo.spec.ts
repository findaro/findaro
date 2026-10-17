import { expect, test, type Page } from "@playwright/test";

// The website's /demo/ page: one page, a Search | AI Mode switch that sets the widget's mode, the tab kept in
// ?mode=. Needs the site rendered with real demo keys (site/README.md) and served at FINDARO_SITE_URL.
test.skip(!process.env.FINDARO_SITE_URL, "set FINDARO_SITE_URL to a rendered copy of site/public");

const w = (page: Page) => page.locator("findaro-search");
const tab = (page: Page, name: RegExp) => page.getByRole("radiogroup", { name: "Demo mode" }).getByRole("radio", { name });
const composer = (page: Page) => w(page).locator(".composer textarea");
const searchBox = (page: Page) => w(page).locator(".box input");

async function settled(page: Page) {
  await expect(w(page).locator(".log .msg.assistant .text").last()).not.toHaveClass(/typing/, { timeout: 20_000 });
}

test("defaults to AI Mode with starters; the switch is a radiogroup", async ({ page }) => {
  await page.goto("/demo/");
  await expect(tab(page, /AI Mode/)).toHaveAttribute("aria-checked", "true");
  await expect(tab(page, /Search/)).toHaveAttribute("aria-checked", "false");
  await expect(w(page)).toHaveAttribute("mode", "ai");
  await expect(w(page).locator(".hello h2")).toBeVisible();
  await expect(w(page).locator(".starters .nrow")).toHaveCount(5);
  await expect(composer(page)).toBeVisible();
  await expect(w(page).locator(".modes")).toBeHidden(); // the page's switch replaces the built-in toggle
});

test("?mode=search opens the Search tab; switching updates the URL and keyboard arrows work", async ({ page }) => {
  await page.goto("/demo/?mode=search");
  await expect(tab(page, /Search/)).toHaveAttribute("aria-checked", "true");
  await expect(searchBox(page)).toBeVisible();
  await expect(w(page).locator(".uhello .starter")).toHaveCount(5);
  await tab(page, /Search/).focus();
  await page.keyboard.press("ArrowRight");
  await expect(tab(page, /AI Mode/)).toHaveAttribute("aria-checked", "true");
  await expect(tab(page, /AI Mode/)).toBeFocused();
  await expect(page).toHaveURL(/[?&]mode=ai/);
  await tab(page, /Search/).click();
  await expect(page).toHaveURL(/[?&]mode=search/);
  await expect(w(page)).toHaveAttribute("mode", "search");
});

test("Search tab: as-you-type results with full cards; the query carries over to AI Mode", async ({ page }) => {
  await page.goto("/demo/?mode=search");
  await searchBox(page).pressSequentially("kaale joote 1000 ke andar", { delay: 15 });
  const cards = w(page).locator(".ugrid .pc");
  await expect(cards.first()).toBeVisible();
  await expect(cards.first().locator(".req")).toContainText(/Matches \d\/\d/);
  await expect(w(page).locator(".chips .chip").filter({ hasText: "Black" })).toBeVisible();
  const req = page.waitForRequest((r) => r.url().endsWith("/v1/chat"));
  await tab(page, /AI Mode/).click();
  expect((await req).postDataJSON().message).toBe("kaale joote 1000 ke andar");
  await settled(page);
  await expect(w(page).locator(".log .msg.user .text").first()).toHaveText("kaale joote 1000 ke andar");
  // back to Search: the earlier results are still there
  await tab(page, /Search/).click();
  await expect(searchBox(page)).toHaveValue("kaale joote 1000 ke andar");
  await expect(cards.first()).toBeVisible();
});

test("Compare in the Search tab switches to AI Mode with the comparison", async ({ page }) => {
  await page.goto("/demo/?mode=search&q=steel%20water%20bottle");
  const boxes = w(page).locator(".ugrid .pc .sel input");
  await expect(boxes.first()).toBeVisible();
  await boxes.nth(0).check();
  await boxes.nth(1).check();
  await w(page).locator(".ubar .selbar").getByRole("button", { name: "Compare" }).click();
  await expect(tab(page, /AI Mode/)).toHaveAttribute("aria-checked", "true");
  await expect(page).toHaveURL(/[?&]mode=ai/);
  await settled(page);
  await expect(w(page).locator(".log .cmp thead th")).toHaveCount(2);
});

test("?q= asks in AI Mode; a follow-up continues the thread", async ({ page }) => {
  await page.goto("/demo/?q=black%20shoes%20under%201000");
  await settled(page);
  await expect(w(page).locator(".log .pc").first()).toBeVisible();
  await expect(page).not.toHaveURL(/[?&]q=/); // a reload doesn't ask again
  await composer(page).fill("only leather");
  await composer(page).press("Enter");
  await expect(w(page).locator(".log .msg.user .text").last()).toHaveText("only leather");
  await settled(page);
  await expect(w(page).locator(".dock .chip").filter({ hasText: "Leather" })).toBeVisible();
});

test("phone: one header, switch and composer visible, no horizontal overflow", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/demo/");
  await expect(page.locator("header")).toHaveCount(1);
  await expect(tab(page, /AI Mode/)).toBeInViewport();
  await expect(composer(page)).toBeInViewport();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});
