import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError, errorMessage } from "../../src/api/client";
import { queryError, validDate } from "../../src/app/validation";

afterEach(() => vi.unstubAllGlobals());
const context = { mailbox: "box +?/#ю", date: "2028-09-11" };
const signal = () => new AbortController().signal;

it("encodes mailbox, message and opaque cursor without changing dates", async () => {
  const mock = vi.fn().mockResolvedValue(new Response("{}"));
  vi.stubGlobal("fetch", mock);
  await api.messages(context, signal(), "opaque+/= ?&ю");
  const url = new URL(mock.mock.calls[0][0], "http://local");
  expect(url.pathname).toBe(
    "/api/v1/mailboxes/box%20%2B%3F%2F%23%D1%8E/messages",
  );
  expect(url.searchParams.get("query_date")).toBe("2028-09-11");
  expect(url.searchParams.get("cursor")).toBe("opaque+/= ?&ю");
  mock.mockResolvedValue(new Response("{}"));
  await api.message(context, "d/?#", signal());
  expect(mock.mock.calls[1][0]).toContain(
    "/messages/d%2F%3F%23?query_date=2028-09-11",
  );
});

it("sends the exact user text and preserves server ordering and scores", async () => {
  const items = [
    { doc_id: "z", score: -1 },
    { doc_id: "a", score: 9 },
  ];
  const mock = vi
    .fn()
    .mockResolvedValue(new Response(JSON.stringify({ items })));
  vi.stubGlobal("fetch", mock);
  const result = await api.search(context, "  вчера & <text>  ", signal());
  expect(result.items).toEqual(items);
  expect(JSON.parse(mock.mock.calls[0][1].body)).toEqual({
    query: "  вчера & <text>  ",
    query_date: context.date,
    limit: 10,
  });
});

it("does not expose a proxy error body or unexpected errors", async () => {
  vi.stubGlobal(
    "fetch",
    vi
      .fn()
      .mockResolvedValue(
        new Response("SQL secret /internal/path", { status: 502 }),
      ),
  );
  await expect(api.mailboxes(signal())).rejects.toMatchObject({
    status: 502,
    code: "http_error",
  });
  expect(errorMessage(new Error("SQL secret"))).not.toContain("secret");
});

it("normalizes network errors and preserves cancellation", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("network")));
  await expect(api.mailboxes(signal())).rejects.toMatchObject({ status: 0 });
  const controller = new AbortController();
  controller.abort();
  const abort = new DOMException("Aborted", "AbortError");
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(abort));
  await expect(api.mailboxes(controller.signal)).rejects.toBe(abort);
});

describe("validation without timezone conversions", () => {
  it.each(["2028-09-11", "2028-02-29", "0001-01-01", "9999-12-31"])(
    "accepts %s",
    (value) => expect(validDate(value)).toBe(true),
  );
  it.each([
    "",
    "2027-02-29",
    "2028-02-30",
    "2028-13-01",
    "0000-01-01",
    "2028-9-11",
    "2028-09-11T00:00:00Z",
  ])("rejects %s", (value) => expect(validDate(value)).toBe(false));
  it("checks blank and oversized queries using code points", () => {
    expect(queryError(" \n\t")).toBeTruthy();
    expect(queryError("я".repeat(4001))).toBeTruthy();
    expect(queryError("😀".repeat(4000))).toBeNull();
    expect(queryError("обычный запрос")).toBeNull();
  });
});

it("distinguishes empty results from engine and readiness errors", () => {
  expect(errorMessage(new ApiError(500, "engine_failure"))).toContain("движка");
  expect(errorMessage(new ApiError(503, "engine_unavailable"))).toContain(
    "не готов",
  );
  expect(errorMessage(new ApiError(404, "mailbox_not_found"))).toContain(
    "Ящик не найден",
  );
});
