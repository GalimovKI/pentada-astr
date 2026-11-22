import { test, expect } from "@playwright/test";
import { cards, mockApi, preview, reply, searchFor } from "./helpers";

test("public landing loads search without prefetching messages or dev controls", async ({ page }) => {
  const paths: string[] = [];
  await mockApi(page, async (_route, url) => { paths.push(url.pathname); return false; });
  await page.goto("./");
  await expect(page.getByRole("button", { name: "Найти", exact: true })).toBeEnabled();
  await expect(page.getByLabel("Найти письмо своими словами")).toBeVisible();
  await expect(page.getByRole("combobox")).toHaveCount(0);
  await expect(page.getByRole("article")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Оценка моделей" })).toHaveCount(0);
  await expect(cards(page)).toHaveCount(0);
  expect([...new Set(paths)]).toEqual(["/api/v1/mailboxes"]);
});

test("search preserves ranking, safe snippets, submitted text and keyboard return", async ({ page }) => {
  const queries: unknown[] = [];
  await mockApi(page, async (route, url) => {
    if (url.pathname.endsWith("/search")) {
      expect(url.searchParams.get("explain")).toBe("true");
      queries.push(route.request().postDataJSON());
    }
    return false;
  });
  await page.goto("./");
  await searchFor(page, "  Важное письмо вчера  ", true);
  await expect(cards(page)).toHaveCount(2);
  await expect(cards(page).first()).toHaveAttribute("id", "message-z");
  await expect(cards(page).nth(1)).toContainText("Фрагмент a");
  await expect(cards(page).first()).toContainText('<img src=x onerror="alert(1)">');
  await expect(cards(page).first().locator("img")).toHaveCount(0);
  expect(queries[0]).toEqual({
    query: "  Важное письмо вчера  ", query_date: "2028-09-11", limit: 10,
    correct_typos: true, expand_word_forms: true,
  });
  await page.getByLabel("Найти письмо своими словами").fill("новый черновик");
  expect(queries).toHaveLength(1);
  await page.getByRole("button", { name: "Найти", exact: true }).click();
  await expect.poll(() => queries.length).toBe(2);
  await cards(page).first().focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("article")).toContainText("Полный текст z");
  await expect(page.getByRole("article")).toContainText("Дата неизвестна");
  await expect(page.getByRole("article")).toContainText("<script>window.hacked=true</script>");
  await expect(page.getByRole("article").getByRole("heading")).toBeFocused();
  expect(await page.evaluate(() => "hacked" in window)).toBe(false);
  await page.getByRole("button", { name: "← К списку" }).click();
  await expect(cards(page).first()).toBeFocused();
  await page.getByRole("button", { name: "Очистить поиск", exact: true }).click();
  await expect(cards(page)).toHaveCount(0);
  await expect(page.getByLabel("Найти письмо своими словами")).toHaveValue("");
});

test("URL can select the search context and invalid context falls back", async ({ page }) => {
  const requests: { path: string; date: string }[] = [];
  await mockApi(page, async (route, url) => {
    if (url.pathname.endsWith("/search")) requests.push({ path: url.pathname, date: route.request().postDataJSON().query_date });
    return false;
  });
  await page.goto("./?mailbox=box-b&date=2029-10-25");
  await searchFor(page);
  await expect(cards(page)).toHaveCount(2);
  await page.goto("./?mailbox=unknown&date=2028-02-30");
  await searchFor(page);
  await expect(cards(page)).toHaveCount(2);
  expect(requests).toEqual([
    {path:"/api/v1/mailboxes/box-b/search",date:"2029-10-25"},
    {path:"/api/v1/mailboxes/box-a/search",date:"2028-09-11"},
  ]);
});

test("invalid queries are rejected locally and empty search shows an empty state", async ({ page }) => {
  let searches = 0;
  await mockApi(page, async (route, url) => {
    if (!url.pathname.endsWith("/search")) return false;
    searches++;
    await reply(route, {items: []});
    return true;
  });
  await page.goto("./");
  await page.getByRole("button", { name: "Найти", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Введите поисковый запрос");
  await searchFor(page, "   ", true);
  await expect(page.getByRole("alert")).toContainText("Введите поисковый запрос");
  await searchFor(page, "я".repeat(4001));
  await expect(page.getByRole("alert")).toContainText("4000");
  expect(searches).toBe(0);
  await searchFor(page);
  await expect(page.getByText("Писем не найдено", {exact:true})).toBeVisible();
  expect(searches).toBe(1);
});

test("bootstrap and unavailable message can both be retried", async ({ page }) => {
  let boxesFailing = true, messageFailing = true;
  await mockApi(page, async (route, url) => {
    if (url.pathname.endsWith("/mailboxes") && boxesFailing) {
      await reply(route, {error:{code:"database_unavailable"}}, 503);
      return true;
    }
    if (url.pathname.includes("/messages/") && messageFailing) {
      await reply(route, {error:{code:"message_not_found"}}, 404);
      return true;
    }
    return false;
  });
  await page.goto("./");
  await expect(page.getByRole("alert")).toContainText("Сервис пока не готов");
  boxesFailing = false;
  await page.getByRole("button", { name:"Повторить" }).click();
  await searchFor(page);
  await cards(page).first().click();
  await expect(page.getByRole("alert")).toContainText("Письмо недоступно");
  messageFailing = false;
  await page.getByRole("button", { name:"Повторить" }).click();
  await expect(page.getByRole("article")).toContainText("Полный текст z");
});

for (const [status, code, message] of [
  [404, "mailbox_not_found", "Ящик не найден"],
  [422, "validation_error", "Сервер отклонил параметры"],
  [500, "engine_failure", "Ошибка поискового движка"],
  [500, "internal_error", "Ошибка сервиса"],
  [503, "service_unavailable", "Сервис пока не готов"],
  [0, "network_error", "Нет связи с сервером"],
] as const) {
  test(`search error ${status}/${code} and retry`, async ({ page }) => {
    let failed = false;
    await mockApi(page, async (route, url) => {
      if (url.pathname.endsWith("/search") && !failed) {
        failed = true;
        if (status === 0) await route.abort("failed");
        else await reply(route, { error: { code } }, status);
        return true;
      }
      return false;
    });
    await page.goto("./");
    await searchFor(page);
    await expect(page.getByRole("alert")).toContainText(message);
    await expect(
      page.getByText("Писем не найдено", { exact: true }),
    ).toHaveCount(0);
    await page.getByRole("button", { name: "Повторить", exact: true }).click();
    await expect(cards(page)).toHaveCount(2);
    await expect(page.getByRole("alert")).toHaveCount(0);
  });
}

test("late search cannot replace newer search or resurrect results after return", async ({
  page,
}) => {
  await mockApi(page, async (route, url) => {
    if (url.pathname.endsWith("/search")) {
      const query = route.request().postDataJSON().query;
      if (query === "старый")
        await new Promise((resolve) => setTimeout(resolve, 500));
      await reply(route, { items: [{ ...preview(query), score: 1 }] });
      return true;
    }
    return false;
  });
  await page.goto("./");
  await searchFor(page, "старый");
  await expect(page.getByText("Выполняем поиск…")).toBeVisible();
  await searchFor(page, "новый");
  await expect(cards(page)).toHaveCount(1);
  await expect(cards(page).first()).toContainText("новый");
  await page.waitForTimeout(600);
  await expect(cards(page).first()).toContainText("новый");
  await searchFor(page, "старый");
  await page.getByRole("button", { name: "Очистить поиск", exact: true }).click();
  await page.waitForTimeout(600);
  await expect(cards(page)).toHaveCount(0);
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("late message cannot replace a later selection", async ({ page }) => {
  await mockApi(page, async (route, url) => {
    if (url.pathname.endsWith("/messages/z")) {
      await new Promise((resolve) => setTimeout(resolve, 500));
      await reply(route, {
        item: {
          doc_id: "z",
          synthetic_user: "box-a",
          doc_dt: null,
          doc: "Устаревшее письмо",
        },
      });
      return true;
    }
    return false;
  });
  await page.goto("./");
  await searchFor(page);
  await cards(page).first().click();
  await expect(page.getByRole("article")).toContainText("Загружаем письмо");
  // On mobile the user returns to the list before selecting the next message.
  await page.getByRole("button", { name: "← К списку" }).click();
  await cards(page).nth(1).click();
  await expect(page.getByRole("article")).toContainText("Полный текст a");
  await page.waitForTimeout(600);
  await expect(page.getByRole("article")).not.toContainText(
    "Устаревшее письмо",
  );
});

test("long IDs and literal multiline text fit the layout", async ({ page }) => {
  const id = "long-id-".repeat(75);
  const body =
    "  Пробелы и переносы\n\n\t<em>Это текст</em>\n" +
    "длиннаястрока".repeat(100);
  await mockApi(page, async (route, url) => {
    if (url.pathname.endsWith("/search")) {
      await reply(route, { items: [{ ...preview(id, body), score: 1 }] });
      return true;
    }
    if (url.pathname.includes("/messages/")) {
      await reply(route, {
        item: { doc_id: id, synthetic_user: "box-a", doc_dt: null, doc: body },
      });
      return true;
    }
    return false;
  });
  await page.goto("./");
  await searchFor(page);
  await expect(cards(page)).toHaveCount(1);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await cards(page).first().click();
  await expect(page.locator(".message-body")).toHaveJSProperty(
    "textContent",
    body,
  );
  await expect(page.locator(".message-body em")).toHaveCount(0);
  expect(
    await page
      .locator(".message-body")
      .evaluate((element) => getComputedStyle(element).whiteSpace),
  ).toBe("pre-wrap");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});
