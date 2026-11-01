/** A proposal and its confirmation receipt share one persisted operation.
 * Keep one card at its first message, retaining the receipt as history text. */
export function ownsTaskResult(messages: readonly {planner_task_id?: string | null}[], index: number) {
  const id = messages[index]?.planner_task_id;
  return Boolean(id) && !messages.slice(0, index).some(message => message.planner_task_id === id);
}
