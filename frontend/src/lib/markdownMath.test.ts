import { describe, expect, it } from "vitest";
import { markdownWithMath } from "./markdownMath";

describe("math survives Markdown parsing", () => {
  it('keeps normal Setext headings and inline math headings while protecting display derivations',()=>{
    expect(markdownWithMath('普通标题\n====\n')).toContain('<h1>普通标题</h1>');
    expect(markdownWithMath(String.raw`行内公式 \(x^2\)
====`)).toContain('<h1>');
    const html=markdownWithMath(String.raw`前置说明
\[
\lim_{x\to0}\frac{e^x-1}{x}
=
1
\]
后续正文`);
    expect(html).toContain('class="math-block"');expect(html).not.toContain('<h1>');
  });
  it('repairs only escaped operator subscripts and preserves text underscores', () => {
    const html = markdownWithMath(String.raw`\[\sum\_{n=1}^{\infty}nx^n\quad\text{file\_name}\]`);
    expect(html).toContain(String.raw`\sum_{n=1}`);
    expect(html).toContain(String.raw`\text{file\_name}`);
    expect(markdownWithMath('`file\\_name`')).toContain('file\\_name');
  });
  it('preserves series, aligned derivations, cases and mixed Chinese without markdown damage', () => {
    const formulas = [
      String.raw`\[\sum_{n=1}^{\infty}nx^n=\frac{x}{(1-x)^2},\quad |x|<1\]`,
      String.raw`\[\begin{aligned}F(x)&=\int_0^x t^2\,dt\\F'(x)&=x^2\end{aligned}\]`,
      String.raw`\[f(x)=\begin{cases}x^2&x\ge0\\-x&x<0\end{cases}\]`,
      String.raw`\[\det\begin{pmatrix}1&2\\3&4\end{pmatrix}=-2\]`,
      String.raw`\(\lim_{x\to0}\frac{\sin x}{x}=1,\ \partial_x f,\ \vec v\in\mathbb R^n\)`,
    ];
    for (const formula of formulas) {
      const html = markdownWithMath('中文讲解：' + formula + '。继续推导。');
      expect(html).toContain('中文讲解：');
      expect(html).toContain(formula.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'));
      expect(html).not.toContain('<em>');
      expect(html).not.toContain('�');
    }
  });
  it("renders explicitly fenced math as protected display math without changing its answer", () => {
    const html = markdownWithMath('```math\nR=\\frac{5\\sqrt{10}}{2}\n```');
    expect(html).toContain(String.raw`\[R=\frac{5\sqrt{10}}{2}\]`);
    expect(html).not.toContain('<pre>');
  });
  it('keeps a real multi-line DeepSeek display formula out of Markdown line-break processing', () => {
    const html = markdownWithMath(String.raw`给你一个例子：

\[
F(x)=\sum_{n=0}^{\infty}\left(\frac{x}{2}\right)^n
=\sum_{n=0}^{\infty}\frac{x^n}{2^n},\qquad |x|<2.
\]

请自己逐项求导。`);
    expect(html).toContain('class="math-block"');
    expect(html).not.toContain('<br>');
    expect(html).toContain(String.raw`\frac{x^n}{2^n}`);
  });
  it("handles malformed bracket display delimiters without Markdown heading artifacts", () => {
    const html = markdownWithMath(String.raw`[
R=\frac{5\sqrt{10}}{2}
=================
]`);
    expect(html).toContain(String.raw`\[R=\frac{5\sqrt{10}}{2}\]`);
    expect(html).not.toContain('<h');
  });
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
