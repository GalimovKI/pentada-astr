export type MailboxOption = {
  id: string;
  name: string;
  example?: string;
};

const featured: MailboxOption[] = [
  { id: "box-12259a301ee2", name: "Штрафы и счета", example: "новый штраф" },
  { id: "box-90560850fd8e", name: "Заказы покупателей", example: "срок отгрузки заказа" },
  { id: "box-84bd433469cb", name: "Контейнерные перевозки", example: "прибытие контейнера" },
];

export function publicMailboxes(available: string[]): MailboxOption[] {
  const options = featured.filter(box => available.includes(box.id));
  for (const id of available) {
    if (options.length === featured.length) break;
    if (!options.some(box => box.id === id)) options.push({ id, name: id });
  }
  return options;
}
