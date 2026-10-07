import { describe, expect, it } from "vitest";
import { markdownWithMath } from "./markdownMath";

describe("math survives Markdown parsing", () => {
  it("preserves parentheses/bracket delimiters, multiline matrix row separators and underscores", () => {
    const text = String.raw`公式 \(x_1^2\) 和
\[
A=\begin{bmatrix}1&-2\\0&3\end{bmatrix}
\]`;
    const html = markdownWithMath(text);
    expect(html).toContain(String.raw`\(x_1^2\)`);
    expect(html).toContain(String.raw`\begin{bmatrix}1&amp;-2\\0&amp;3\end{bmatrix}`);
    expect(html).toContain("\\[\n");
    expect(html).not.toContain('<em>');
  });
  it("preserves dollar math without Markdown emphasis or line breaks within formulas", () => {
    const html = markdownWithMath(String.raw`$a_n+b_n$ and $$x_1+x_2$$`);
    expect(html).toContain('$a_n+b_n$');
    expect(html).toContain('$$x_1+x_2$$');
    expect(html).not.toContain('<em>');
  });
  it("keeps inline code and fenced pseudocode in code tags", () => {
    const html = markdownWithMath('`\\(x\\)`\n\n```text\n\\[A\\]\nif a[mid] < x: l = mid\n```');
    expect(html).toContain('<code>\\(x\\)</code>');
    expect(html).toContain('if a[mid] &lt; x: l = mid');
    expect(html).toContain('<pre><code');
  });
  it("escapes embedded HTML within protected math rather than trusting model text", () => {
    const html = markdownWithMath(String.raw`\(<img src=x onerror=alert(1)>\)`);
    expect(html).not.toContain('<img');
    expect(html).toContain('&lt;img');
  });
});
