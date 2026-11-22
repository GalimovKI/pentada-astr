import { useEffect } from "react";
import { api, type Mailboxes } from "../api/client";
import { Failure } from "../components/Status";
import { MailSession } from "./MailSession";
import { useTask } from "./useTask";
import { validDate } from "./validation";

export function App() {
  const { data, error, run } = useTask<Mailboxes>();
  useEffect(() => { void run(api.mailboxes); }, [run]);
  const params = new URLSearchParams(window.location.search);
  const linkedMailbox = params.get("mailbox") ?? "";
  const mailbox = data?.items.includes(linkedMailbox) ? linkedMailbox : data?.items[0];
  const linkedDate = params.get("date") ?? "";
  const date = validDate(linkedDate) ? linkedDate : "2028-09-11";
  return (
    <MailSession context={mailbox ? { mailbox, date } : undefined}>
      {error != null && <Failure error={error} retry={() => void run(api.mailboxes)} />}
      {data && !mailbox && <p role="status" className="status">Нет доступных ящиков.</p>}
    </MailSession>
  );
}
