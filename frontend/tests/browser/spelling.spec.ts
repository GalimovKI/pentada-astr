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

test("search offers inline corrections and silently expands valid related words", async ({ page, isMobile }) => {
  const searches: unknown[] = [];
  await mockApi(page, async (route, url) => {
    if (url.pathname.endsWith("/spelling")) {
      const {query, cursor, expand_word_forms} = route.request().postDataJSON();
      expect(expand_word_forms).toBe(true);
      const item = {start:0, end:cursor, original:query, replacement:"штраф"};
      await reply(route, {
        changes: query === "штрфа" ? [item] : [],
        completions: query === "испр" ? [{...item,replacement:"исправить"}] : [],

      });
      return true;
    }
    if (url.pathname.endsWith("/search")) searches.push(route.request().postDataJSON());
    return false;
  });

  await page.goto("./");
  const field = page.getByLabel("Найти письмо своими словами");
  await field.fill("испр");
  const completion = page.getByRole("button", {name:"исправить",exact:true});
  await expectInsideField(field, completion);
  await field.press("Tab");
  await expect(field).toHaveValue("исправить");
  await field.fill("штрфа");
  const fix = page.getByRole("button", {name:"Заменить штрфа на штраф"});
  await expectInsideField(field, fix);
  if (isMobile) await fix.tap(); else await fix.click();
  await expect(field).toHaveValue("штраф");
  await field.fill("штрафик");
  await expect(page.getByRole("button", {name:/Подставить родственное слово/})).toHaveCount(0);
  await field.press("Enter");
  await expect.poll(() => searches.at(-1)).toMatchObject({
    query:"штрафик", correct_typos:true, expand_word_forms:true,
  });
  await expect(field).toHaveValue("штрафик");
});
