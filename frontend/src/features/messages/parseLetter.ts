// The corpus stores the envelope and the plain-text body in a single string.
// Only read consecutive headers at the start; quoted headers belong to the body.
export function parseLetter(text: string) {
  let sender = "";
  let subject = "";
  let recipient = "";
  let body = text;
  const header = /^(от|отправитель|from|кому|to|тема|subject):[ \t]*([^\r\n]*)(?:\r?\n|$)/i;
  while (true) {
    const match = header.exec(body);
    if (!match) break;
    const field = match[1].toLowerCase();
    const value = match[2].trim();
    if (field === "тема" || field === "subject") {
      if (subject) break;
      subject = value;
    } else if (field === "кому" || field === "to") {
      if (recipient) break;
      recipient = value;
    } else {
      if (sender) break;
      sender = value;
    }
    body = body.slice(match[0].length);
  }
  if (body !== text) body = body.replace(/^([ \t]*\r?\n)+/, "");
  body = body.replace(/^текст письма:[ \t]*/i, "");
  return { sender, subject, recipient, body };
}
