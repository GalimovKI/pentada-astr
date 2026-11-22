import { test, expect, type Locator } from "@playwright/test";
import { mockApi, reply } from "./helpers";

async function expectInsideField(input: Locator, hint: Locator) {
  await expect(hint).toBeVisible();
  const [field, button] = await Promise.all([input.boundingBox(), hint.boundingBox()]);
  if (!field || !button) throw new Error("Expected a visible search field and an inline suggestion");
  expect(button.y).toBeGreaterThanOrEqual(field.y - 1);
  expect(button.y + button.height).toBeLessThanOrEqual(field.y + field.height + 1);
  expect(button.x).toBeGreaterThanOrEqual(field.x - 1);
  expect(button.x + button.width).toBeLessThanOrEqual(field.x + field.width + 1);
}

test("suggestions change only accepted words and silent search preserves the draft", async ({ page, isMobile }) => {
  const searches: Array<{ query: string; correct_typos?: boolean; expand_word_forms?: boolean }> = [];
  await mockApi(page, async (route, url) => {
    if (url.pathname === "/api/v1/features") {
      await reply(route, { evaluations: true, mail_models: [{ id: "bm25", name: "BM25" }] });
      return true;
    }
    if (url.pathname === "/api/v1/spelling") {
      await reply(route, { completions: [], changes: [{ start: 2, end: 7, original: "штрфа", replacement: "штраф" }] });
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
  await expectInsideField(query, suggestion);
  await query.press("Enter");
  await expect.poll(() => searches.at(-1)?.query).toBe("📩 штрфа");
  await query.fill("");
  await query.fill("📩 штрфа");
  await expectInsideField(query, suggestion);
  if (isMobile) await suggestion.tap();
  else await suggestion.click();
  await expect(query).toHaveValue("📩 штраф");
  await page.getByRole("button", { name: "Исправлять при поиске" }).click();
  await query.fill("штрфа");
  await query.press("Enter");
  await expect.poll(() => searches.at(-1)?.correct_typos).toBe(true);
  await expect(query).toHaveValue("штрфа");
  expect(searches.at(-1)).not.toHaveProperty("expand_word_forms");
  await expect(suggestion).toHaveCount(0);
  await page.getByRole("button", { name: "Выкл." }).click();
  await query.press("Enter");
  await expect.poll(() => searches.length).toBe(3);
  expect(searches.at(-1)).not.toHaveProperty("correct_typos");
  expect(searches.at(-1)).not.toHaveProperty("expand_word_forms");
});

test("inline completions respect the caret, keyboard acceptance, dismissal and trailing spaces", async ({ page }) => {
  const word = "испр";
  await mockApi(page, async (route, url) => {
    if (url.pathname.endsWith("/features")) {
      await reply(route, { evaluations: true, mail_models: [{ id: "bm25", name: "BM25" }] });
      return true;
    }
    if (url.pathname.endsWith("/spelling")) {
      const { query, cursor } = route.request().postDataJSON();
      const start = cursor - word.length;
      const atPrefix = Array.from(query).slice(start, cursor).join("") === word;
      await reply(route, { changes: [], completions: atPrefix ? [
        { start, end: cursor, original: word, replacement: "исправить" },
        { start, end: cursor, original: word, replacement: "исправь" },
      ] : [] });
      return true;
    }
    return false;
  });
  await page.goto("./");
  const query = page.getByLabel("Найти письмо своими словами");
  await page.getByRole("button", { name: "Подсказывать при вводе" }).click();
  await query.fill(word);
  const completion = page.getByRole("button", { name: "исправить", exact: true });
  await expectInsideField(query, completion);
  await expect(query).toHaveValue(word);
  await query.press("Escape");
  await expect(completion).toBeHidden();
  await expect(query).toHaveValue(word);
  await expect(query).toBeFocused();
  await query.press("Backspace");
  await query.pressSequentially("р");
  await expectInsideField(query, completion);
  await query.press("Tab");
  await expect(query).toHaveValue("исправить");
  await expect(query).toBeFocused();
  await query.fill(word);
  await expectInsideField(query, completion);
  await query.press("Space");
  await expect(completion).toHaveCount(0);
  await query.fill("📩 испр завтра");
  // Home moves the viewport on macOS. Place the caret just before the last
  // prefix character, then move it as a user would. Selection offsets are UTF-16.
  await query.evaluate(input => (input as HTMLInputElement).setSelectionRange(6, 6));
  await query.press("ArrowRight");
  await expect(completion).toBeVisible();
  await completion.click();
  await expect(query).toHaveValue("📩 исправить завтра");
  await expect(query).toBeFocused();
  await query.press("!");
  await expect(query).toHaveValue("📩 исправить! завтра");
});


test("combined mode suggests related words and corrects submitted queries after a reload", async ({ page }) => {
  const searches: Array<{ query: string; correct_typos?: boolean; expand_word_forms?: boolean }> = [];
  await mockApi(page, async (route, url) => {
    if (url.pathname.endsWith("/features")) {
      await reply(route, { evaluations: true, mail_models: [{ id: "bm25", name: "BM25" }] });
      return true;
    }
    if (url.pathname.endsWith("/spelling")) {
      const { query, expand_word_forms } = route.request().postDataJSON();
      const change = { start: 0, end: query.length, original: query, replacement: "штраф" };
      await reply(route, {
        changes: query === "штрфа" ? [change] : [],
        completions: query === "штрафик" ? [{ ...change, replacement: "штрафики" }] : [],
        related: expand_word_forms && query === "штрафик" ? [change] : [],
      });
      return true;
    }
    if (url.pathname.endsWith("/search")) searches.push(route.request().postDataJSON());
    return false;
  });
  await page.goto("./");
  const mode = page.getByRole("button", { name: "При вводе и поиске", exact: true });
  await mode.click();
  await page.reload();
  await expect(mode).toHaveAttribute("aria-pressed", "true");
  const query = page.getByLabel("Найти письмо своими словами");
  await query.fill("штрафик");
  const related = page.getByRole("button", { name: "Подставить родственное слово «штраф»" });
  await expectInsideField(query, related);
  await expect(related).toHaveText("Также штраф");
  await query.press("Enter");
  await expect.poll(() => searches.at(-1)).toMatchObject({
    query: "штрафик", correct_typos: true, expand_word_forms: true,
  });
  await expect(query).toHaveValue("штрафик");
  await query.fill("штрфа");
  await expectInsideField(query, page.getByRole("button", { name: "Заменить штрфа на штраф" }));
  await query.press("Enter");
  await expect.poll(() => searches.at(-1)).toMatchObject({
    query: "штрфа", correct_typos: true, expand_word_forms: true,
  });
  await query.fill("штрафик");
  await related.click();
  await expect(query).toHaveValue("штраф");
  await query.press("Enter");
  await expect.poll(() => searches.at(-1)).toMatchObject({
    query: "штраф", correct_typos: true, expand_word_forms: true,
  });
});
