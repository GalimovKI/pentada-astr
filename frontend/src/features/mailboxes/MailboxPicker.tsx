import type { Context, Mailboxes } from "../../api/client";

type Selection = Pick<Context, "mailbox" | "dataset">;

export function MailboxPicker({ boxes, mailbox, dataset, onChange }: Selection & {
  boxes: Mailboxes;
  onChange: (value: Selection) => void;
}) {
  const extraArchives = boxes.archives?.filter(archive => archive.id !== "mail-public");
  return (
    <div className="field">
      <label htmlFor="mailbox">Почтовый ящик</label>
      <select id="mailbox" value={dataset ?? mailbox} onChange={event => {
        const value = event.currentTarget.value;
        const archive = extraArchives?.find(item => item.id === value);
        onChange(archive ? { mailbox: archive.mailbox, dataset: archive.id } : { mailbox: value });
      }}>
        {boxes.items.map(item => <option key={item} value={item}>{item}</option>)}
        {extraArchives?.map(archive =>
          <option key={archive.id} value={archive.id}>{archive.name} · {archive.total.toLocaleString("ru-RU")}</option>
        )}
      </select>
    </div>
  );
}
