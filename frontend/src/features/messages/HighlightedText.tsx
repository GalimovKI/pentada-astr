import type { Passage } from "../../api/client";

// The API sends positions in the original document. Render React text nodes
// so even markup-looking mail stays literal and offsets include emoji correctly.
export function HighlightedText({ text, offset, passage }: {
  text: string;
  offset: number;
  passage?: Passage | null;
}) {
  if (!passage) return <>{text}</>;
  const pieces = [];
  let cursor = 0;
  for (const [a, b] of passage.ranges) {
    const start = passage.offset + a - offset;
    const end = passage.offset + b - offset;
    if (start < cursor || end > text.length || start >= end) continue;
    pieces.push(text.slice(cursor, start), <mark key={start}>{text.slice(start, end)}</mark>);
    cursor = end;
  }
  return <>{pieces}{text.slice(cursor)}</>;
}
