import type { Context, Mailboxes } from "../../api/client";

type Selection = Pick<Context, "mailbox" | "dataset">;

export function MailboxPicker({ boxes, mailbox, dataset, onChange }: Selection & {
  boxes: Mailboxes;
  onChange: (value: Selection) => void;
}) {
  const primary = boxes.items.map(item => <option key={item} value={item}>{item}</option>);
  return (
    <div className="field">
      <label htmlFor="mailbox">Почтовый ящик</label>
      <select id="mailbox" value={dataset ? JSON.stringify([dataset, mailbox]) : mailbox}
        onChange={event => {
          const option = event.currentTarget.selectedOptions[0];
          onChange({ mailbox: option.dataset.mailbox ?? option.value, dataset: option.dataset.corpus });
        }}>
        {boxes.groups?.length ? <optgroup label="Почтовый поиск">{primary}</optgroup> : primary}
        {boxes.groups?.map(group => <optgroup key={group.id} label={group.name}>
          {group.items.map(item => <option key={item} value={JSON.stringify([group.id, item])}
            data-corpus={group.id} data-mailbox={item}>{item} · {group.name}</option>)}
        </optgroup>)}
      </select>
    </div>
  );
}
