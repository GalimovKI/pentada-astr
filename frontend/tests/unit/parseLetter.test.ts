import { expect, it } from "vitest";
import { parseLetter } from "../../src/features/messages/parseLetter";

it("separates the order notification envelope from its body", () => {
  const text = "ОТ: mail-36f1bfff7a@example.invalid\nТЕМА: Есть новый заказ\nТЕКСТ ПИСЬМА: Его нужно обработать.\n\nДо 21:00.";
  expect(parseLetter(text)).toEqual({
    sender: "mail-36f1bfff7a@example.invalid",
    subject: "Есть новый заказ",
    recipient: "",
    body: "Его нужно обработать.\n\nДо 21:00.",
  });
});

it("preserves quoted headers, markup and indentation inside the body", () => {
  const body = "  <b>Добрый день</b>\r\n\r\nОт: Анна\r\nТема: Пересылка";
  expect(parseLetter(body).body).toBe(body);
  const letter = parseLetter("Отправитель: Иван\r\nКому: Анна\r\nТема: Отчёт\r\n\r\n" + body);
  expect(letter).toEqual({ sender: "Иван", recipient: "Анна", subject: "Отчёт", body });
});
