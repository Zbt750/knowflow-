import type { GenerationConfirmation } from "../api/personalQuestions";

export type GenerationConfirmationReply =
  | { kind: "not-confirmation" }
  | { kind: "needs-node" }
  | { kind: "unmatched-node"; requested: string }
  | { kind: "confirm"; kpId: string }
  | { kind: "confirm-targets"; targets: NonNullable<GenerationConfirmation["proposed_targets"]> };

/**
 * Resolve a short chat reply to the existing pending generation confirmation.
 * Never guess between multiple knowledge nodes: the user must select one in
 * the card or include its exact name/code in the confirmation message.
 */
export function resolveGenerationConfirmationReply(
  input: string,
  confirmation: GenerationConfirmation,
): GenerationConfirmationReply {
  const text = input.trim();
  const match = text.match(/^(我确定|我确认|确定|确认|生成吧|生成|可以|好的|好|行|接受此方案|接受这个方案|就按这个(?:生成)?)(?:\s*[:：,，+＋]?\s*(.*))?$/u);
  if (!match) return { kind: "not-confirmation" };

  const detail = (match[2] ?? "").trim();
  if (confirmation.proposed_targets?.length) {
    if (!detail || /^(?:全部|按此分配|就按这个|按这个方案)$/u.test(detail)) {
      return { kind: "confirm-targets", targets: confirmation.proposed_targets };
    }
    return { kind: "needs-node" };
  }
  if (detail) {
    const exactNode = confirmation.nodes.find(
      (node) => node.name.trim() === detail || node.code.trim() === detail,
    );
    if (exactNode) return { kind: "confirm", kpId: exactNode.kp_id };
    return { kind: "unmatched-node", requested: detail };
  }

  const selected = confirmation.nodes.find(
    (node) => node.kp_id === confirmation.selected_kp_id,
  );
  if (selected) return { kind: "confirm", kpId: selected.kp_id };
  if (confirmation.nodes.length === 1) {
    return { kind: "confirm", kpId: confirmation.nodes[0].kp_id };
  }
  return { kind: "needs-node" };
}
