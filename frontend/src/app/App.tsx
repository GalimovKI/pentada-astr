import { useEffect, useState } from "react";
import { api, type Mailboxes } from "../api/client";
import { Failure } from "../components/Status";
import { MailSession } from "./MailSession";
import { publicMailboxes } from "./publicMailboxes";
import { useTask } from "./useTask";
import { validDate } from "./validation";

export function App() {
  const { data, error, run } = useTask<Mailboxes>();
  useEffect(() => { void run(api.mailboxes); }, [run]);
  const [requestedMailbox, setRequestedMailbox] = useState(() =>
    new URLSearchParams(window.location.search).get("mailbox") ?? "");
  const params = new URLSearchParams(window.location.search);
  const options = publicMailboxes(data?.items ?? []);
  const mailbox = data?.items.includes(requestedMailbox) ? requestedMailbox : options[0]?.id;
  const linkedDate = params.get("date") ?? "";
  const date = validDate(linkedDate) ? linkedDate : "2028-09-11";
  function chooseMailbox(id: string) {
    const url = new URL(window.location.href);
    url.searchParams.set("mailbox", id);
    window.history.replaceState(window.history.state, "", url);
    setRequestedMailbox(id);
  }
  return (
    <MailSession context={mailbox ? { mailbox, date } : undefined}
      mailboxes={options} onMailboxChange={chooseMailbox}>
      {error != null && <Failure error={error} retry={() => void run(api.mailboxes)} />}
      {data && !mailbox && <p role="status" className="status">Нет доступных ящиков.</p>}
    </MailSession>
  );
}
