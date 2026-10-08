import { expect, test } from "@playwright/test";

test("React example (headless SDK): search, remove chip, ask", async ({ page }) => {
  await page.goto("/");
  await page.getByPlaceholder("Search or ask…").fill("kaale joote 1000 ke andar");
  await expect(page.getByRole("button", { name: "Black ×" })).toBeVisible();
  await expect(page.locator("li").first()).toBeVisible();
  await page.getByRole("button", { name: "Black ×" }).click();
  await expect(page.getByRole("button", { name: "Black ×" })).toHaveCount(0);
  await page.getByRole("button", { name: "Ask AI" }).click();
  await expect(page.getByTestId("answer")).not.toBeEmpty({ timeout: 20_000 });
});
