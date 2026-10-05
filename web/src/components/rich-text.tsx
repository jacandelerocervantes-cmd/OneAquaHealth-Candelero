import { Fragment, type ReactNode } from "react";

/**
 * The only formatting an answer may show: **bold** and "- " bullet lines. Everything else stays plain text; nothing is
 * ever interpreted as HTML or as a link (the server already withholds answers with markup or web addresses).
 */
function inline(line: string): ReactNode[] {
  return line.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") && part.length > 4 ? <strong key={i}>{part.slice(2, -2)}</strong> : <Fragment key={i}>{part.replace(/\*\*/g, "")}</Fragment>,
  );
}

export function RichText({ text, testId }: { text: string; testId: string }) {
  const blocks: ReactNode[] = [];
  let bullets: string[] = [];
  const flush = () => {
    if (bullets.length) {
      const items = bullets;
      blocks.push(
        <ul key={`ul${blocks.length}`} className="list-disc space-y-1 pl-5">
          {items.map((b, i) => (
            <li key={i}>{inline(b)}</li>
          ))}
        </ul>,
      );
      bullets = [];
    }
  };
  for (const raw of text.split("\n")) {
    const bullet = /^\s*[-•]\s+(.*)$/.exec(raw);
    if (bullet) {
      bullets.push(bullet[1] ?? "");
      continue;
    }
    flush();
    if (raw.trim() !== "") blocks.push(<p key={`p${blocks.length}`}>{inline(raw)}</p>);
  }
  flush();
  return (
    <div data-testid={testId} className="space-y-2 break-words leading-relaxed">
      {blocks}
    </div>
  );
}
