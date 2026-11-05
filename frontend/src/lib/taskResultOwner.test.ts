import { expect, it } from 'vitest';
import { ownsTaskResult } from './taskResultOwner';
it('keeps one stable card for a proposal and its persisted confirmation receipt', () => {
  const history=[{planner_task_id:'task-1'},{planner_task_id:'task-1'},{planner_task_id:null}];
  expect(history.map((_,index)=>ownsTaskResult(history,index))).toEqual([true,false,false]);
  expect(history).toHaveLength(3);
});
it('retains distinct operations without attaching one to a new QA message', () => {
  const history=[{planner_task_id:'old'},{planner_task_id:null},{planner_task_id:'new'}];
  expect(history.map((_,index)=>ownsTaskResult(history,index))).toEqual([true,false,true]);
});
