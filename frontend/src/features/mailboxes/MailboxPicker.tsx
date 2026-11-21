export function MailboxPicker({
  items,
  value,
  onChange,
}: {
  items: string[];
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="field">
      <label htmlFor="mailbox">Почтовый ящик</label>
      <select
        id="mailbox"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        {items.map((item) => (
          <option key={item} value={item}>
            {item}
          </option>
        ))}
      </select>
    </div>
  );
}
