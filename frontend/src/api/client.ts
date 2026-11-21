export interface Preview {
  doc_id: string;
  synthetic_user: string;
  doc_dt: string | null;
  snippet: string;
}
export interface Message extends Omit<Preview, "snippet"> {
  doc: string;
}
export interface Hit extends Preview {
  score: number;
}
export interface Mailboxes {
  items: string[];
}
export interface Messages {
  items: Preview[];
  next_cursor: string | null;
}
export interface SearchResponse {
  items: Hit[];
}
export interface MessageResponse {
  item: Message;
}
export interface Context {
  mailbox: string;
  date: string;
}
export interface SearchBody {
  query: string;
  query_date: string;
  limit: number;
}
export const QUERY_MAX_LENGTH = 4000;

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
  ) {
    super("API request failed");
  }
}

async function request<T>(
  path: string,
  signal: AbortSignal,
  body?: SearchBody,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      signal,
      ...(body
        ? {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          }
        : {}),
    });
  } catch (error) {
    if (signal.aborted) throw error;
    throw new ApiError(0, "network_error");
  }
  if (!response.ok) {
    let code = "http_error";
    try {
      const payload: unknown = await response.json();
      if (
        typeof payload === "object" &&
        payload !== null &&
        "error" in payload
      ) {
        const detail = payload.error;
        if (
          typeof detail === "object" &&
          detail !== null &&
          "code" in detail &&
          typeof detail.code === "string"
        )
          code = detail.code;
      }
    } catch {
      /* A proxy can return a non-JSON error. Never expose its body. */
    }
    throw new ApiError(response.status, code);
  }
  try {
    return (await response.json()) as T;
  } catch {
    throw new ApiError(response.status, "invalid_response");
  }
}

const mailboxPath = (context: Context) =>
  `/mailboxes/${encodeURIComponent(context.mailbox)}`;
export const api = {
  mailboxes: (signal: AbortSignal) => request<Mailboxes>("/mailboxes", signal),
  messages: (context: Context, signal: AbortSignal, cursor?: string) => {
    const params = new URLSearchParams({
      query_date: context.date,
      limit: "50",
    });
    if (cursor !== undefined) params.set("cursor", cursor);
    return request<Messages>(
      `${mailboxPath(context)}/messages?${params}`,
      signal,
    );
  },
  message: (context: Context, id: string, signal: AbortSignal) => {
    const params = new URLSearchParams({ query_date: context.date });
    return request<MessageResponse>(
      `${mailboxPath(context)}/messages/${encodeURIComponent(id)}?${params}`,
      signal,
    );
  },
  search: (context: Context, query: string, signal: AbortSignal) =>
    request<SearchResponse>(`${mailboxPath(context)}/search`, signal, {
      query,
      query_date: context.date,
      limit: 10,
    }),
};

export function errorMessage(error: unknown): string {
  if (!(error instanceof ApiError))
    return "Не удалось получить ответ сервиса. Повторите попытку.";
  if (error.code === "mailbox_not_found")
    return "Ящик не найден. Выберите другой ящик.";
  if (error.code === "message_not_found" || error.status === 404)
    return "Письмо недоступно в выбранном ящике на эту дату.";
  if (error.status === 422)
    return "Проверьте запрос и дату сценария. Сервер отклонил параметры.";
  if (error.status === 503)
    return "Сервис пока не готов. Попробуйте ещё раз немного позже.";
  if (
    error.code === "engine_failure" ||
    error.code === "engine_contract_violation"
  )
    return "Ошибка поискового движка. Попробуйте повторить поиск.";
  if (error.status === 500) return "Ошибка сервиса. Попробуйте ещё раз.";
  if (error.status === 0)
    return "Нет связи с сервером. Проверьте подключение и запуск backend.";
  return "Не удалось получить ответ сервиса. Повторите попытку.";
}
