import { test, expect } from "@playwright/test";
import { parseLetter } from "../../src/features/messages/parseLetter";
import { cards } from "../browser/helpers";
import type {
  Mailboxes,
  Messages,
  SearchResponse,
  MessageResponse,
} from "../../src/api/client";

// Read-only test against the existing imported official corpus and current BM25.
// This is an integration scenario, not an assessment of search quality.
test("prepared local corpus: browse, paginate, search, read and change context", async ({
  page,
  request,
}, testInfo) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  const boxesResponse = await request.get("/api/v1/mailboxes");
  expect(boxesResponse.ok()).toBe(true);
  const boxes = (await boxesResponse.json()) as Mailboxes;
  expect(boxes.items).toContain("box-84bd433469cb");
  await page.goto("/");
  await page.getByLabel("Почтовый ящик").selectOption(boxes.archives?.length ? "mail-public" : "box-84bd433469cb");
  await page.getByLabel("Почта на дату", { exact: true }).fill("2028-09-11");
  const path = boxes.archives?.length ? "/api/v1/mailboxes/%40archive" : "/api/v1/mailboxes/box-84bd433469cb";
  const messages = (await (
    await request.get(`${path}/messages?query_date=2028-09-11&limit=50`)
  ).json()) as Messages;
  await expect(cards(page)).toHaveCount(messages.items.length);
  await expect(cards(page).first()).toHaveId(`message-${messages.items[0].doc_id}`);
  await page.getByRole("button", { name: "Загрузить ещё" }).click();
  await expect(cards(page)).toHaveCount(100);
  const query =
    "Найди уведомления о завершении досмотра контейнеров, полученные вчера";
  const expected = (await (
    await request.post(`${path}/search`, {
      data: { query, query_date: "2028-09-11", limit: 10 },
    })
  ).json()) as SearchResponse;
  expect(expected.items.length).toBeGreaterThan(0);
  await page.getByLabel("Найти письмо своими словами").fill(query);
  await page.getByLabel("Найти письмо своими словами").press("Enter");
  await expect(cards(page)).toHaveCount(expected.items.length);
  await expect(page.locator(".receipt-date time")).toHaveAttribute("datetime", "2028-09-10");
  const match = await cards(page).first().locator("mark").first().innerText();
  for (let i = 0; i < expected.items.length; i++)
    await expect(cards(page).nth(i)).toHaveId(`message-${expected.items[i].doc_id}`);
  await page.screenshot({
    path: testInfo.outputPath("search.png"),
    fullPage: true,
  });
  await cards(page).first().focus();
  await page.keyboard.press("Enter");
  const full = (await (
    await request.get(
      `${path}/messages/${encodeURIComponent(expected.items[0].doc_id)}?query_date=2028-09-11`,
    )
  ).json()) as MessageResponse;
  await expect(page.getByRole("article").locator("mark").first()).toHaveText(match);
  const letter = parseLetter(full.item.doc);
  await expect(page.locator(".message-body")).toHaveJSProperty("textContent", letter.body);
  await expect(
    page.getByRole("heading", { name: letter.subject || "Без темы", exact: true }),
  ).toBeFocused();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath("reader.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "← К списку" }).click();
  await expect(cards(page).first()).toBeFocused();
  await page.getByLabel("Почта на дату", { exact: true }).fill("2014-01-01");
  await expect(
    page.getByRole("heading", { name: "Результаты поиска" }),
  ).toHaveCount(0);
  await expect(page.getByRole("article")).toHaveCount(0);
  await expect(page.getByLabel("Найти письмо своими словами")).toHaveValue("");
  const early = (await (
    await request.get(`${path}/messages?query_date=2014-01-01&limit=50`)
  ).json()) as Messages;
  await expect(cards(page)).toHaveCount(early.items.length);
  await page.getByLabel("Почтовый ящик").selectOption(boxes.archives?.[0]?.id ?? boxes.items[0]);
  await expect(page.getByRole("heading", { name: "Все письма" })).toBeVisible();
  expect(errors).toEqual([]);
});

test("dev tabs preserve the open letter and evaluation selection", async ({ page, request }) => {
  const features = await request.get("/api/v1/features");
  test.skip(!features.ok() || !(await features.json()).evaluations, "Dev site only");
  await page.goto("/");
  const tabs = page.getByRole("navigation", { name: "Вкладки dev-сайта" });
  const mail = tabs.getByRole("link", { name: "Почта", exact: true });
  const evaluation = tabs.getByRole("link", { name: "Оценка моделей" });
  await expect(mail).toHaveAttribute("aria-current", "page");
  await cards(page).first().click();
  const body = page.locator(".message-body");
  await expect(body).toBeVisible();
  const original = await body.textContent();
  await evaluation.click();
  await expect(evaluation).toHaveAttribute("aria-current", "page");
  await expect(body).toBeHidden();
  const model = page.locator("#evaluations").getByLabel("Модель поиска");
  await model.selectOption("bm25-stemmed");
  await mail.click();
  await expect(body).toBeVisible();
  await expect(body).toHaveJSProperty("textContent", original);
  await expect(page.getByLabel("Модель поиска писем")).toHaveValue("bm25-event-aware");
  await page.goBack();
  await expect(model).toHaveValue("bm25-stemmed");
});

test("dev mail reruns the submitted query with the selected model", async ({ page, request }) => {
  const features = await request.get("/api/v1/features");
  test.skip(!features.ok() || !(await features.json()).mail_models, "Dev mail model selector only");
  await page.goto("/");
  const picker = page.getByLabel("Модель поиска писем");
  await expect(picker.locator("option")).toHaveCount(4);
  await page.getByLabel("Почтовый ящик").selectOption("mail-public");
  await page.getByLabel("Почта на дату", { exact: true }).fill("2028-09-11");
  const query = "Найди уведомления о завершении досмотра контейнеров, полученные вчера";
  const field = page.getByLabel("Найти письмо своими словами");
  await field.fill(query);
  await field.press("Enter");
  await expect(cards(page).first()).toBeVisible();
  await field.fill("черновик");
  const response = page.waitForResponse(r => new URL(r.url()).searchParams.get("model") === "bm25");
  await picker.selectOption("bm25");
  const reply = await response;
  expect(reply.ok()).toBe(true);
  expect(reply.request().postDataJSON().query).toBe(query);
  const hits = (await reply.json()).items;
  expect(hits.length).toBeGreaterThan(0);
  await expect(cards(page).first()).toHaveId(`message-${hits[0].doc_id}`);
  await expect(field).toHaveValue("черновик");
});
