import {describe,it,expect} from 'vitest';
import {questionSourceLabel} from './questionSourceLabel';
describe('result provenance is a stored category, not a model assertion',()=>{
 it('keeps personal AI, originals, imports and unknown categories distinct',()=>{
  expect(questionSourceLabel('personal_ai_practice')).toBe('个人 AI 练习');
  expect(questionSourceLabel('development_original')).toBe('开发原创');
  expect(questionSourceLabel('exam_curated')).toBe('真题改编（整理）');
  expect(questionSourceLabel('exam_variant')).toBe('真题改编（变式）');
  expect(questionSourceLabel('exam_curated')).not.toContain('原版');
  expect(questionSourceLabel('unclassified_public')).toContain('待核');
  expect(questionSourceLabel('imported_reference')).toContain('imported_reference');
 });
});
