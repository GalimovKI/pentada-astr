import { test, expect } from "@playwright/test";
import { cards, mockApi, preview, reply, searchFor } from "./helpers";

test("mailboxes, date, opaque pagination, opening and keyboard return", async ({
  page,
}) => {
  const requests: URL[] = [];
  await mockApi(page, async (_route, url) => {
    requests.push(url);
    return false;
  });
  await page.goto("/");
  await expect(page.getByLabel("Почтовый ящик")).toHaveValue("box-a");
  await expect(cards(page)).toHaveCount(2);
  expect(
    requests.filter((url) => /\/messages\//.test(url.pathname)),
  ).toHaveLength(0);
  await expect(
    page.getByText("Дата неизвестна", { exact: true }),
  ).toBeVisible();
  await page.getByLabel("Почтовый ящик").selectOption("box-b");
  await expect(cards(page).first()).toContainText("box-b-1");
  await page.getByLabel("Дата сценария", { exact: true }).fill("2029-10-25");
  await expect
    .poll(
      () =>
        requests.filter(
          (url) => url.searchParams.get("query_date") === "2029-10-25",
        ).length,
    )
    .toBeGreaterThan(0);
  await expect(cards(page)).toHaveCount(2);
  await page.getByRole("button", { name: "Загрузить ещё" }).click();
  await expect(cards(page)).toHaveCount(3);
  expect(requests.at(-1)?.searchParams.get("cursor")).toBe("opaque +/=?&");
  await cards(page).first().focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("article")).toContainText("Полный текст box-b-1");
  await expect(
    page.getByRole("heading", { name: "Письмо", exact: true }),
  ).toBeFocused();
  await expect(page.getByRole("article")).toContainText(
    "<script>window.hacked=true</script>",
  );
  expect(await page.evaluate(() => "hacked" in window)).toBe(false);
  await page.getByRole("button", { name: "← К списку" }).click();
  await expect(cards(page).first()).toBeFocused();
  await expect(page.getByRole("button", { name: "Загрузить ещё" })).toHaveCount(
    0,
  );
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});

test("search by Enter and button preserves ranking, draft is separate, text is safe", async ({
  page,
}) => {
  const queries: unknown[] = [];
  await mockApi(page, async (route, url) => {
    if (url.pathname.endsWith("/search"))
      queries.push(route.request().postDataJSON());
    return false;
  });
  await page.goto("/");
  await searchFor(page, "  Важное письмо вчера  ", true);
  await expect(cards(page)).toHaveCount(2);
  await expect(cards(page).first()).toContainText("z");
  await expect(cards(page).nth(1)).toContainText("Фрагмент a");
  await expect(cards(page).first()).toContainText(
    '<img src=x onerror="alert(1)">',
  );
  expect(await cards(page).first().locator("img").count()).toBe(0);
  expect(queries[0]).toEqual({
    query: "  Важное письмо вчера  ",
    query_date: "2028-09-11",
    limit: 10,
  });
  await page.getByLabel("Найти письмо своими словами").fill("новый черновик");
  await expect(page.locator(".submitted")).toContainText("Важное письмо вчера");
  expect(queries).toHaveLength(1);
  await page.getByRole("button", { name: "Найти", exact: true }).click();
  await expect(page.locator(".submitted")).toContainText("новый черновик");
  await cards(page).first().click();
  await expect(page.getByRole("article")).toContainText("Полный текст z");
  await expect(page.getByRole("article")).toContainText("Дата неизвестна");
  await page.getByRole("button", { name: "← К списку" }).click();
  await page.getByRole("button", { name: "Все письма", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Все письма" })).toBeVisible();
});

test("blank, whitespace, long query and missing date are rejected locally", async ({
  page,
}) => {
  let searches = 0;
  await mockApi(page, async (_route, url) => {
    if (url.pathname.endsWith("/search")) searches++;
    return false;
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Найти", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(
    "Введите поисковый запрос",
  );
  await searchFor(page, "   ", true);
  await expect(page.getByRole("alert")).toContainText(
    "Введите поисковый запрос",
  );
  await searchFor(page, "я".repeat(4001));
  await expect(page.getByRole("alert")).toContainText("4000");
  expect(searches).toBe(0);
  await page.getByLabel("Дата сценария", { exact: true }).fill("");
  await expect(page.getByRole("alert")).toContainText("корректную дату");
  await expect(cards(page)).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Найти", exact: true }),
  ).toHaveCount(0);
});

test("empty mailbox and empty search are distinct", async ({ page }) => {
  await mockApi(page, async (route, url) => {
    if (url.pathname.endsWith("/messages")) {
      await reply(route, { items: [], next_cursor: null });
      return true;
    }
    if (url.pathname.endsWith("/search")) {
      await reply(route, { items: [] });
      return true;
    }
    return false;
  });
  await page.goto("/");
  await expect(page.getByText("Здесь пока нет писем")).toBeVisible();
  await searchFor(page);
  await expect(
    page.getByText("Писем не найдено", { exact: true }),
  ).toBeVisible();
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
    await page.goto("/");
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

test("mailbox bootstrap and unavailable message can be retried", async ({
  page,
}) => {
  let boxesFailing = true;
  let messageFailing = true;
  await mockApi(page, async (route, url) => {
    if (url.pathname === "/api/v1/mailboxes" && boxesFailing) {
      await reply(route, { error: { code: "database_unavailable" } }, 503);
      return true;
    }
    if (/\/messages\//.test(url.pathname) && messageFailing) {
      await reply(route, { error: { code: "message_not_found" } }, 404);
      return true;
    }
    return false;
  });
  await page.goto("/");
  await expect(page.getByRole("alert")).toContainText("Сервис пока не готов");
  boxesFailing = false;
  await page.getByRole("button", { name: "Повторить" }).click();
  await cards(page).first().click();
  await expect(page.getByRole("alert")).toContainText("Письмо недоступно");
  messageFailing = false;
  await page.getByRole("button", { name: "Повторить" }).click();
  await expect(page.getByRole("article")).toContainText("Полный текст box-a-1");
});

test("pagination error keeps loaded messages and retries the same cursor", async ({
  page,
}) => {
  let attempts = 0;
  await mockApi(page, async (route, url) => {
    if (url.searchParams.has("cursor")) {
      attempts++;
      if (attempts === 1) {
        await reply(route, { error: { code: "database_unavailable" } }, 503);
        return true;
      }
    }
    return false;
  });
  await page.goto("/");
  await page.getByRole("button", { name: "Загрузить ещё" }).click();
  await expect(page.getByRole("alert")).toBeVisible();
  await expect(cards(page)).toHaveCount(2);
  await page.getByRole("button", { name: "Повторить" }).click();
  await expect(cards(page)).toHaveCount(3);
  expect(attempts).toBe(2);
});

test("mailbox and date switches discard search, selection, cursor and delayed old lists", async ({
  page,
}) => {
  await mockApi(page, async (route, url) => {
    if (url.pathname.includes("box-b") && url.pathname.endsWith("/messages")) {
      await new Promise((resolve) => setTimeout(resolve, 400));
      await reply(route, { items: [preview("old-box-b")], next_cursor: null });
      return true;
    }
    return false;
  });
  await page.goto("/");
  await searchFor(page);
  await expect(cards(page).first()).toContainText("z");
  await cards(page).first().click();
  await expect(page.getByRole("article")).toBeVisible();
  await page.getByLabel("Почтовый ящик").selectOption("box-b");
  await expect(page.getByRole("article")).toHaveCount(0);
  await expect(
    page.getByRole("heading", { name: "Результаты поиска" }),
  ).toHaveCount(0);
  await expect(cards(page)).toHaveCount(0);
  await page.getByLabel("Почтовый ящик").selectOption("box-a");
  await expect(cards(page).first()).toContainText("box-a-1");
  await page.waitForTimeout(500);
  await expect(page.getByText("old-box-b", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Загрузить ещё" }).click();
  await expect(cards(page)).toHaveCount(3);
  await searchFor(page);
  await expect(cards(page).first()).toContainText("z");
  await cards(page).first().click();
  await page.getByLabel("Дата сценария", { exact: true }).fill("2029-01-01");
  await expect(page.getByRole("article")).toHaveCount(0);
  await expect(page.getByLabel("Найти письмо своими словами")).toHaveValue("");
  await expect(cards(page)).toHaveCount(2);
});

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
  await page.goto("/");
  await searchFor(page, "старый");
  await expect(page.getByRole("status")).toContainText("Выполняем поиск");
  await searchFor(page, "новый");
  await expect(cards(page)).toHaveCount(1);
  await expect(cards(page).first()).toContainText("новый");
  await page.waitForTimeout(600);
  await expect(cards(page).first()).toContainText("новый");
  await searchFor(page, "старый");
  await page.getByRole("button", { name: "Все письма", exact: true }).click();
  await page.waitForTimeout(600);
  await expect(cards(page).first()).toContainText("box-a-1");
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("late message cannot replace a later selection", async ({ page }) => {
  await mockApi(page, async (route, url) => {
    if (url.pathname.endsWith("/messages/box-a-1")) {
      await new Promise((resolve) => setTimeout(resolve, 500));
      await reply(route, {
        item: {
          doc_id: "box-a-1",
          synthetic_user: "box-a",
          doc_dt: null,
          doc: "Устаревшее письмо",
        },
      });
      return true;
    }
    return false;
  });
  await page.goto("/");
  await cards(page).first().click();
  await expect(page.getByRole("article")).toContainText("Загружаем письмо");
  // On mobile the user returns to the list before selecting the next message.
  await page.getByRole("button", { name: "← К списку" }).click();
  await cards(page).nth(1).click();
  await expect(page.getByRole("article")).toContainText("Полный текст box-a-2");
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
    if (url.pathname.endsWith("/messages")) {
      await reply(route, { items: [preview(id, body)], next_cursor: null });
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
  await page.goto("/");
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
