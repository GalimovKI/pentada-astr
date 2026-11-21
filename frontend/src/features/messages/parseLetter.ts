// The corpus stores the envelope and the plain-text body in a single string.
// Only read consecutive headers at the start; quoted headers belong to the body.
export function parseLetter(text: string) {
  let sender = "";
  let subject = "";
  let recipient = "";
  let body = text;
  const offsets = { sender: 0, subject: 0, recipient: 0, body: 0 };
  const header = /^(от|отправитель|sender|from|получатели|recipients|кому|to|тема|subject):[ \t]*([^\r\n]*)(?:\r?\n|$)/i;
  while (true) {
    const match = header.exec(body);
    if (!match) break;
    const field = match[1].toLowerCase();
    const value = match[2].trim();
    const start = text.length - body.length + match[0].indexOf(":") + 1;
    const offset = start + text.slice(start).search(/\S|$/);
    if (field === "тема" || field === "subject") {
      if (subject) break;
      subject = value;
      offsets.subject = offset;
    } else if (["кому", "to", "получатели", "recipients"].includes(field)) {
      if (recipient) break;
      recipient = value;
      offsets.recipient = offset;
    } else {
      if (sender) break;
      sender = value;
      offsets.sender = offset;
    }
    body = body.slice(match[0].length);
  }
  if (body !== text) {
    body = body.replace(/^(?:файл|file):[^\r\n]*\r?\n={3,}[ \t]*\r?\n/i, "");
    body = body.replace(/^([ \t]*\r?\n)+/, "");
  }
  body = body.replace(/^текст письма:[ \t]*/i, "");
  offsets.body = text.length - body.length;
  return { sender, subject, recipient, body, offsets };
}
