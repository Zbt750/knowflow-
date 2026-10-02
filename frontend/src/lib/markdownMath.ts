import { Marked } from "marked";

// Consume complete math spans before Markdown interprets escapes, emphasis or breaks.
// Code spans/fences remain ordinary Markdown code and are never rendered by KaTeX.
const mathStart = /\\\(|\\\[|\$\$|\$(?!\s)/;
const mathSpan = /^(?:\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\]|\$\$[\s\S]*?\$\$|\$(?!\s)(?:\\.|[^$\n])*?\$(?!\d))/;
const escapeHtml = (text: string) => text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const parser = new Marked({ gfm: true, breaks: true }, { extensions: [{
  name: "preservedMath",
  level: "inline",
  start(source: string) { return source.search(mathStart) < 0 ? undefined : source.search(mathStart); },
  tokenizer(source: string) {
    const match = source.match(mathSpan);
    if (match) return { type: "preservedMath", raw: match[0] };
  },
  renderer(token) { return escapeHtml(token.raw); },
}] });

// Caller MUST sanitize the resulting HTML before inserting it into the DOM.
export function markdownWithMath(text: string): string {
  return parser.parse(text, { async: false }) as string;
}
