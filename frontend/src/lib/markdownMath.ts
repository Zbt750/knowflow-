import { Marked } from "marked";

// Consume complete math spans before Markdown interprets escapes, emphasis or breaks.
// 普通代码块保持原样；明确标为 math/latex 的块交给 KaTeX。
const mathStart = /\\\(|\\\[|\$\$|\$(?!\s)/;
const mathSpan = /^(?:\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\]|\$\$[\s\S]*?\$\$|\$(?!\s)(?:\\.|[^$\n])*?\$(?!\d))/;
const escapeHtml = (text: string) => text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
// Only repair a Markdown-escaped subscript immediately following a named math
// operator. Preserve literal underscores in text/code and all other LaTeX.
const normalizeOperatorSubscripts = (text: string) => text.replace(/\\(sum|prod|lim|int|oint|bigcup|bigcap)\\_([\w{])/g, "\\$1_$2");
const parser = new Marked({ gfm: true, breaks: true, tokenizer: {
  lheading(source) {
    // Marked tries Setext headings BEFORE paragraph/startBlock extensions.
    // Prose + a display derivation with a standalone '=' can consequently
    // swallow the opening math delimiter. Let paragraph splitting reach our
    // math block tokenizer first; ordinary Markdown headings keep the default.
    const heading = this.rules.block.lheading.exec(source);
    if (heading && /(?:\\\[|\$\$|^\s*\[\s*$)/m.test(heading[0])) return undefined;
    return false;
  },
} }, { extensions: [{
  name: "displayMathBlock",
  level: "block",
  start(source: string) { return source.search(/^(?:\s*```(?:math|latex|tex)\s*$|\s*(?:\\)?\[\s*$)/m); },
  tokenizer(source: string) {
    const fenced = source.match(/^\s*```(?:math|latex|tex)\s*\n([\s\S]*?)\n\s*```[^\S\n]*(?:\n|$)/);
    // 兼容模型把 \\[...\\] 写成单独 [ 和 ] 的情形。只接纳明显的 LaTeX，避免误改列表。
    const delimited = !fenced && source.match(/^\s*\\\[\s*\n([\s\S]*?)\n\s*\\\][^\S\n]*(?:\n|$)/);
    const bracketed = !fenced && !delimited && source.match(/^\s*\[\s*\n([\s\S]*?)\n\s*\]\s*(?:\n|$)/);
    const match = fenced || delimited || bracketed;
    if (!match || (bracketed && !/\\(?:frac|sqrt|lim|begin|int|sum|left|right)|[_^]/.test(match[1]))) return;
    let body = normalizeOperatorSubscripts(match[1].trim());
    body = body.replace(/^(?:\\\[|\$\$)\s*/, "").replace(/\s*(?:\\\]|\$\$)$/, "");
    // 仅去除展示块中误插入的 Markdown 分隔行，不改数学内容或补算答案。
    body = body.replace(/^\s*={3,}\s*$/gm, "").trim();
    if (delimited) body = `\n${body}\n`;
    return { type: "displayMathBlock", raw: match[0], body };
  },
  renderer(token) { return `<div class="math-block">\\[${escapeHtml(token.body as string)}\\]</div>`; },
}, {
  name: "preservedMath",
  level: "inline",
  start(source: string) { return source.search(mathStart) < 0 ? undefined : source.search(mathStart); },
  tokenizer(source: string) {
    const match = source.match(mathSpan);
    if (match) return { type: "preservedMath", raw: match[0], body: normalizeOperatorSubscripts(match[0]) };
  },
  renderer(token) { return escapeHtml(token.body as string); },
}] });

// Caller MUST sanitize the resulting HTML before inserting it into the DOM.
// 轻量 ASCII 数学预处理：仅处理“整行纯 ASCII 且含明确数学记号”的行，
// 已有 LaTeX/代码块不触碰，普通中英文句子不转换。
const asciiMathLine = /^(?=[^\u4e00-\u9fff]*$)(?=.*(?:lim\s*\(|sqrt\s*\(|[A-Za-z]\s*[\^_]|dy\s*\/\s*dx))[A-Za-z0-9\s+\-*/^_=()\[\]{}.,<>|!\\]+$/;
function normalizeAsciiMath(text: string): string {
  if (/\$\$|\$|\\\(|\\\[|```/.test(text)) return text;
  return text.split("\n").map((line) => {
    const trimmed = line.trim();
    if (!trimmed || trimmed.length > 140 || !asciiMathLine.test(trimmed)) return line;
    const body = trimmed
      .replace(/\bsqrt\s*\(([^()]*)\)/g, "\\sqrt{$1}")
      .replace(/->/g, "\\to ")
      .replace(/\blim\s*\(([^()]*)\)/g, "\\lim_{$1}")
      .replace(/\bd([A-Za-z])\s*\/\s*d([A-Za-z])\b/g, "\\frac{d$1}{d$2}");
    return `$${body}$`;
  }).join("\n");
}
export function markdownWithMath(text: string): string {
  return parser.parse(normalizeAsciiMath(text), { async: false }) as string;
}
