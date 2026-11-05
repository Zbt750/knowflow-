/** Read-only presentation adapter for legacy authored explanations.
 * Never rewrite question/version content or infer a new mathematical answer.
 */
export type CalculationFact = {label: string; value: string};
export function answerExplanation(text: string): {text: string; facts: CalculationFact[]; raw: string | null} {
  const original = {text, facts: [] as CalculationFact[], raw: null};
  const heading = /(?:^|\r?\n)#{1,6}[ \t]+可复核计算[\/／]轨迹[ \t]*\r?\n/.exec(text);
  if (!heading) return original;
  const start = heading.index + heading[0].length;
  const tail = text.slice(start);
  const nextHeading = /\r?\n(?=#{1,6}[ \t]+)/.exec(tail);
  const end = nextHeading?.index ?? tail.length;
  const raw = tail.slice(0, end).trim();
  const json = raw.replace(/^```(?:json)?[ \t]*\r?\n([\s\S]*?)\r?\n```$/i, '$1');
  let parsed: unknown;
  try { parsed = JSON.parse(json); } catch { return original; }
  if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') return original;
  const labels: Record<string, string> = {ratio_limit: '比值判别法的极限', interval: '收敛范围', radius: '收敛半径', final_value: '计算结果'};
  const values: Record<string, string> = {harmonic_divergent: '调和级数，发散', convergent: '收敛', divergent: '发散', absolute_convergent: '绝对收敛', conditional_convergent: '条件收敛'};
  const facts = Object.entries(parsed).map(([key, value]) => {
    const boundary = /^boundary_([a-zA-Z])(-?\d+(?:\.\d+)?)$/.exec(key);
    return {
      label: labels[key] ?? (boundary ? `边界 ${boundary[1]}=${boundary[2]}` : `计算记录（${key}）`),
      value: typeof value === 'string' ? values[value] ?? value : JSON.stringify(value),
    };
  });
  if (!facts.length) return original;
  return {text: [text.slice(0, heading.index).trimEnd(), tail.slice(end).trimStart()].filter(Boolean).join('\n\n'), facts, raw};
}
