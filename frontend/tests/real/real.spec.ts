import { test, expect } from "@playwright/test";
import { type Mailboxes, type SearchResponse, type MessageResponse } from "../../src/api/client";
import { parseLetter } from "../../src/features/messages/parseLetter";
import { cards, searchFor } from "../browser/helpers";

test("public search uses the real corpus and opens only returned messages", async ({ page, request }, info) => {
  const errors: string[] = [];
  page.on("pageerror", e => errors.push(e.message));
  const box = "box-84bd433469cb", date = "2028-09-11";
  const boxes = await request.get("./api/v1/mailboxes");
  expect(boxes.ok()).toBe(true);
  expect(((await boxes.json()) as Mailboxes).items).toContain(box);
  await page.goto(`./?mailbox=${box}&date=${date}`);
  await expect(cards(page)).toHaveCount(0);
  await expect(page.getByRole("button", {name:"Найти",exact:true})).toBeEnabled();
  await page.screenshot({path:info.outputPath("landing.png"),fullPage:true});
  const query = "Найди уведомления о завершении досмотра контейнеров, полученные вчера";
  const endpoint = `./api/v1/mailboxes/${box}`;
  const response = await request.post(`${endpoint}/search?explain=true`, {
    data:{query, query_date:date, limit:10, correct_typos:true, expand_word_forms:true},
  });
  expect(response.ok()).toBe(true);
  const expected = (await response.json()) as SearchResponse;
  expect(expected.items.length).toBeGreaterThan(0);
  await searchFor(page, query, true);
  await expect(cards(page)).toHaveCount(expected.items.length);
  for (const [i,item] of expected.items.entries())
    await expect(cards(page).nth(i)).toHaveId("message-" + item.doc_id);
  await page.screenshot({path:info.outputPath("results.png"),fullPage:true});
  await cards(page).first().focus();
  await page.keyboard.press("Enter");
  const message = await request.get(`${endpoint}/messages/${encodeURIComponent(expected.items[0].doc_id)}?query_date=${date}`);
  expect(message.ok()).toBe(true);
  const letter = parseLetter(((await message.json()) as MessageResponse).item.doc);
  await expect(page.locator(".message-body")).toHaveText(letter.body);
  await expect(page.getByRole("article").getByRole("heading")).toBeFocused();
  await page.screenshot({path:info.outputPath("reader.png"),fullPage:true});
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole("button", {name:"← К списку"}).click();
  await expect(cards(page).first()).toBeFocused();
  await page.getByRole("button", {name:"Очистить поиск", exact:true}).click();
  await expect(cards(page)).toHaveCount(0);
  await expect(page.getByLabel("Найти письмо своими словами")).toHaveValue("");
  expect(errors).toEqual([]);
});
