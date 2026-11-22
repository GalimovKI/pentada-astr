import { test, expect } from "@playwright/test";
import { mockApi, reply } from "./helpers";

test("suggestions change only accepted words and silent search preserves the draft", async ({ page }) => {
  const searches: Array<{ query: string; correct_typos?: boolean }> = [];
  await mockApi(page, async (route, url) => {
    if (url.pathname === "/api/v1/features") {
      await reply(route, { evaluations: true, mail_models: [{ id: "bm25", name: "BM25" }] });
      return true;
    }
    if (url.pathname === "/api/v1/spelling") {
      await reply(route, { changes: [{ start: 2, end: 7, original: "штрфа", replacement: "штраф" }] });
      return true;
    }
    if (url.pathname.endsWith("/search")) searches.push(route.request().postDataJSON());
    return false;
  });
  await page.goto("./");
  const query = page.getByLabel("Найти письмо своими словами");
  await page.getByRole("button", { name: "Подсказывать при вводе" }).click();
  await query.fill("📩 штрфа");
  const suggestion = page.getByRole("button", { name: "Заменить штрфа на штраф" });
  await expect(suggestion).toBeVisible();
  await query.press("Enter");
  await expect.poll(() => searches.at(-1)?.query).toBe("📩 штрфа");
  await suggestion.click();
  await expect(query).toHaveValue("📩 штраф");
  await page.getByRole("button", { name: "Исправлять при поиске" }).click();
  await query.fill("штрфа");
  await query.press("Enter");
  await expect.poll(() => searches.at(-1)?.correct_typos).toBe(true);
  await expect(query).toHaveValue("штрфа");
  await expect(suggestion).toHaveCount(0);
  await page.getByRole("button", { name: "Выкл." }).click();
  await query.press("Enter");
  await expect.poll(() => searches.length).toBe(3);
  expect(searches.at(-1)).not.toHaveProperty("correct_typos");
});
