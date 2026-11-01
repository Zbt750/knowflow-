import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import katex from 'katex';
import { markdownWithMath } from './markdownMath';

const fixture = JSON.parse(readFileSync(new URL('../../../tests/fixtures/geometric_actual_reference_20261024.json', import.meta.url), 'utf8'));

describe('2026-10-24 actual geometric series QuestionVersion', () => {
  it('preserves the exact two sums before KaTeX; no escaping or Markdown flattening', () => {
    const html = markdownWithMath(fixture.stem);
    const formulas = [...html.matchAll(/\\\(([\s\S]*?)\\\)/g)].map(match => match[1]);
    expect(formulas).toEqual([
      String.raw`\sum_{n=1}^{\infty} \frac{1}{2^n}`,
      String.raw`\sum_{n=1}^{\infty} \left(\frac{3}{2}\right)^n`,
    ]);
    expect(html).not.toContain('<em>');
    expect(html).not.toContain('∑n=1∞12n');
    for (const tex of formulas) {
      const rendered = katex.renderToString(tex, { throwOnError: true, trust: false, output: 'htmlAndMathml' });
      expect(rendered).toContain('<mfrac>');
      expect(rendered).toContain('<msup>');
      expect(rendered).toContain('application/x-tex');
      expect(rendered).not.toContain('katex-error');
    }
  });

  it('also preserves and parses every inline formula in the saved explanation', () => {
    const html = markdownWithMath(fixture.explanation);
    const formulas = [...html.matchAll(/\\\(([\s\S]*?)\\\)/g)].map(match => match[1].replaceAll('&lt;', '<').replaceAll('&gt;', '>'));
    expect(formulas).toHaveLength(6);
    for (const tex of formulas) expect(() => katex.renderToString(tex, { throwOnError: true, trust: false })).not.toThrow();
    expect(fixture.correct_answer).toBe('B');
  });
});
