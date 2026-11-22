import type { Page, Route } from "@playwright/test";
export const preview = (
  id: string,
  snippet = `Фрагмент ${id}`,
  date: string | null = "2028-09-10",
  box = "box-a",
) => ({ doc_id: id, synthetic_user: box, doc_dt: date, snippet });
export async function reply(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}
export async function mockApi(
  page: Page,
  custom?: (route: Route, url: URL) => Promise<boolean>,
) {
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const base = process.env.APP_BASE_PATH || "/";
    if (base !== "/") {
      if (!url.pathname.startsWith(base + "api/"))
        throw new Error(`API request escaped environment: ${url.pathname}`);
      url.pathname = "/" + url.pathname.slice(base.length);
    }
    if (custom && (await custom(route, url))) return;
    if (url.pathname === "/api/v1/mailboxes")
      return reply(route, { items: ["box-a", "box-b"] });
    if (url.pathname.endsWith("/search"))
      return reply(route, {
        items: [
          {
            ...preview(
              "z",
              '<img src=x onerror="alert(1)"> Важное письмо',
              null,
            ),
            score: 0.1,
          },
          { ...preview("a"), score: 9.9 },
        ],
      });
    if (url.pathname === "/api/v1/spelling")
      return reply(route, { changes: [], completions: [], related: [] });
    if (!/\/mailboxes\/[^/]+\/messages\/[^/]+$/.test(url.pathname))
      throw new Error(`Unexpected public mail request: ${url.pathname}`);
    const id = decodeURIComponent(url.pathname.split("/").at(-1)!);
    return reply(route, {
      item: {
        doc_id: id,
        synthetic_user: "box-a",
        doc_dt: null,
        doc: `Полный текст ${id}\n  <script>window.hacked=true</script>\nСтрока 3`,
      },
    });
  });
}
export const cards = (page: Page) =>
  page.getByRole("list", { name: "Письма", exact: true }).getByRole("button");
export async function searchFor(
  page: Page,
  text = "Важное письмо",
  enter = false,
) {
  await page.getByLabel("Найти письмо своими словами").fill(text);
  if (enter)
    await page.getByLabel("Найти письмо своими словами").press("Enter");
  else await page.getByRole("button", { name: "Найти", exact: true }).click();
}
