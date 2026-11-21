import { expect, it } from "vitest";
import { parseLetter } from "../../src/features/messages/parseLetter";

it("separates the order notification envelope from its body", () => {
  const text = "ОТ: mail-36f1bfff7a@example.invalid\nТЕМА: Есть новый заказ\nТЕКСТ ПИСЬМА: Его нужно обработать.\n\nДо 21:00.";
  expect(parseLetter(text)).toMatchObject({
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
  expect(letter).toMatchObject({ sender: "Иван", recipient: "Анна", subject: "Отчёт", body });
});

it.each([
  ["Subject: Test\nSender: A\nRecipients: B\nFile: a/inbox/1."],
  ["Тема: Test\nОтправитель: A\nПолучатели: B\nФайл: a/inbox/1."],
])("reads an EnronQA envelope and preserves body offsets", header => {
  const text = header + "\n=====================================\nHello!";
  const letter = parseLetter(text);
  expect(letter).toMatchObject({ subject: "Test", sender: "A", recipient: "B", body: "Hello!" });
  expect(text.slice(letter.offsets.body)).toBe(letter.body);
});
