import { expect, test, type Page } from "@playwright/test";

// The unified demo (examples/plain-html/unified.html → unified-demo.html with the demo keys): one box, search as you
// type, Enter asks the assistant, which refines the same grid. Locators pierce the shadow root.
const w = (page: Page) => page.locator("findaro-search");
const input = (page: Page) => w(page).locator(".box input");
const cards = (page: Page) => w(page).locator(".ugrid .pc");
const panel = (page: Page) => w(page).locator(".panel");
const reply = (page: Page) => panel(page).locator(".msg.assistant");
const chips = (page: Page) => w(page).locator(".chips .chip");

async function settle(page: Page) {
  await expect(reply(page).locator(".text")).not.toHaveClass(/typing/, { timeout: 20_000 });
}

async function ask(page: Page, q: string) {
  await input(page).fill(q);
  await input(page).press("Enter");
  await expect(panel(page).locator(".msg.user .text")).toHaveText(q);
  await settle(page);
}

const ids = (page: Page) => cards(page).evaluateAll((els) => els.map((el) => el.getAttribute("data-id")));

test.beforeEach(async ({ page }) => {
  await page.goto("/unified-demo.html");
  await expect(input(page)).toBeVisible();
});

test("empty state: hint and starter chips, no mode toggle", async ({ page }) => {
  await expect(w(page).locator(".uhello p")).toBeVisible();
  await expect(w(page).locator(".uhello .starter")).toHaveCount(5);
  await expect(w(page).locator(".modes")).toBeHidden();
  await expect(panel(page)).toBeHidden();
});

test("typing searches as you type (no LLM, no chat)", async ({ page }) => {
  let chats = 0;
  page.on("request", (r) => { if (r.url().endsWith("/v1/chat")) chats++; });
  const req = page.waitForRequest((r) => r.url().endsWith("/v1/search") && r.postDataJSON()?.llm === false);
  await input(page).pressSequentially("steel water bottle", { delay: 20 });
  await req;
  await expect(cards(page).first()).toBeVisible();
  await expect(panel(page)).toBeHidden();
  expect(chats).toBe(0);
});

test("Enter asks: panel with How I searched and next steps, chips, requirement line on cards", async ({ page }) => {
  const req = page.waitForRequest((r) => r.url().endsWith("/v1/chat"));
  await ask(page, "black shoes under 1000");
  expect((await req).postDataJSON().message).toBe("black shoes under 1000");
  await expect(input(page)).toHaveValue("");
  await expect(chips(page).filter({ hasText: "Under ₹1,000" })).toBeVisible();
  await expect(chips(page).filter({ hasText: "Black" })).toBeVisible();
  await expect(reply(page).locator(".how summary")).toContainText(/Searched in/);
  await expect(panel(page).locator(".clarify .nrow").first()).toBeVisible();
  await expect(cards(page).first().locator(".req")).toContainText(/Matches \d\/\d/);
  await expect(w(page).getByRole("button", { name: "New search" })).toBeVisible();
});

test("a follow-up refines the same session; earlier turns fold away", async ({ page }) => {
  let sid = "";
  page.on("response", async (r) => {
    if (r.url().endsWith("/v1/chat") && !sid) sid = ((await r.text()).match(/"session_id":\s*"([^"]+)"/) ?? [])[1] ?? "";
  });
  await ask(page, "steel water bottle");
  const before = await cards(page).count();
  const req = page.waitForRequest((r) => r.url().endsWith("/v1/chat") && !!r.postDataJSON()?.session_id);
  await ask(page, "only copper");
  expect((await req).postDataJSON().session_id).toBe(sid);
  await expect(chips(page).filter({ hasText: "Copper" })).toHaveCount(1);
  await expect(panel(page).locator(".earlier summary")).toContainText("(1)");
  expect(await cards(page).count()).toBeLessThanOrEqual(before);
});

test("a question about the results answers in the panel and keeps the grid", async ({ page }) => {
  await ask(page, "black shoes under 1000");
  const shown = await ids(page);
  await ask(page, "is the first one leather?");
  await expect(reply(page).locator(".text")).not.toBeEmpty();
  expect(await ids(page)).toEqual(shown);
});

test("a next-step row applies its patch in the same session", async ({ page }) => {
  await ask(page, "steel water bottle");
  const row = panel(page).locator(".clarify .nrow[data-clarify=next]").first();
  await expect(row).toBeVisible();
  const label = (await row.locator("span").first().innerText()).trim();
  const req = page.waitForRequest((r) => r.url().endsWith("/v1/chat") && !!r.postDataJSON()?.patch?.length);
  await row.click();
  expect((await req).postDataJSON().message).toBe("");
  await expect(panel(page).locator(".msg.user .text")).toHaveText(label);
  await settle(page);
});

test("removing a chip after a question continues the session", async ({ page }) => {
  await ask(page, "kaale joote 1000 ke andar");
  const req = page.waitForRequest((r) => r.url().endsWith("/v1/chat") && !!r.postDataJSON()?.patch?.length
    && !!r.postDataJSON()?.session_id);
  await chips(page).filter({ hasText: "Black" }).getByRole("button").click();
  // chips from a chat turn carry the full PatchOp shape (unused keys as null)
  expect((await req).postDataJSON().patch).toMatchObject([{ op: "remove_filter", field: "color", value: "Black" }]);
  await settle(page);
  await expect(chips(page).filter({ hasText: "Black" })).toHaveCount(0);
  await expect(chips(page).filter({ hasText: "Under ₹1,000" })).toBeVisible();
});

test("select two products and compare them; a third is fine, a fourth is refused", async ({ page }) => {
  await ask(page, "steel water bottle");
  const boxes = w(page).locator(".pc .sel input");
  await boxes.nth(0).check();
  await boxes.nth(1).check();
  const bar = w(page).locator(".ubar .selbar");
  await expect(bar).toContainText("2 selected");
  const req = page.waitForRequest((r) => r.url().endsWith("/v1/chat") && r.postDataJSON()?.product_ids?.length === 2);
  await bar.getByRole("button", { name: "Compare" }).click();
  expect((await req).postDataJSON().message).toBe("Compare these");
  await settle(page);
  const table = reply(page).locator(".cmp");
  await expect(table).toBeVisible();
  await expect(table.locator("thead th")).toHaveCount(2);
  await boxes.nth(2).check();
  await boxes.nth(3).click();
  await expect(boxes.nth(3)).not.toBeChecked();
  await expect(w(page).locator(".ubar .notice")).toBeVisible();
});

test("Ask about these sends the next message with the selected products", async ({ page }) => {
  await ask(page, "steel water bottle");
  await w(page).locator(".pc .sel input").nth(0).check();
  await w(page).locator(".ubar .selbar").getByRole("button", { name: "Ask about these" }).click();
  await expect(input(page)).toBeFocused();
  const req = page.waitForRequest((r) => r.url().endsWith("/v1/chat") && r.postDataJSON()?.product_ids?.length === 1);
  await input(page).fill("is it insulated?");
  await input(page).press("Enter");
  expect((await req).postDataJSON().message).toBe("is it insulated?");
  await settle(page);
});

test("Ask on a card opens the product drawer", async ({ page }) => {
  await ask(page, "women shoes under 1k");
  await cards(page).first().locator(".act[data-ask]").click();
  const drawer = w(page).locator(".drawer");
  await expect(drawer).toBeVisible();
  await expect(drawer.locator("#zd-title")).not.toBeEmpty();
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
});

test("New search resets the session", async ({ page }) => {
  await ask(page, "steel water bottle");
  await w(page).getByRole("button", { name: "New search" }).click();
  await expect(panel(page)).toBeHidden();
  await expect(cards(page)).toHaveCount(0);
  await expect(w(page).locator(".uhello .starter").first()).toBeVisible();
  const req = page.waitForRequest((r) => r.url().endsWith("/v1/chat"));
  await ask(page, "kurta for a wedding");
  expect((await req).postDataJSON().session_id ?? null).toBeNull();
});

test("phone: one column, no horizontal scroll, selection bar docked at the bottom", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await ask(page, "black shoes under 1000");
  await w(page).locator(".pc .sel input").nth(0).check();
  const bar = w(page).locator(".ubar .selbar");
  await expect(bar).toBeVisible();
  const box = await bar.boundingBox();
  expect(box!.y + box!.height).toBeGreaterThan(844 - 120);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});
