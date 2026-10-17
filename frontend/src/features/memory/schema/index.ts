import { z } from 'zod';

import { MemoryCreateKind } from '@/api-client/model';

export const memorySchema = z.object({
  kind: z.nativeEnum(MemoryCreateKind),
  content: z.string().trim().min(1, '내용을 입력하세요.').max(1000),
});
export type MemoryForm = z.infer<typeof memorySchema>;

export const decisionSchema = z.object({
  title: z.string().trim().min(1, '결정을 입력하세요.'),
  choice: z.string().trim().min(1, '선택한 안을 입력하세요.'),
  rationale: z.string().trim().min(1, '선택 이유를 입력하세요.'),
  alternatives: z.string(),
  expected_outcome: z.string(),
  review_on: z.string(),
});
export type DecisionForm = z.infer<typeof decisionSchema>;

export const EMPTY_DECISION: DecisionForm = { title: '', choice: '', rationale: '', alternatives: '', expected_outcome: '', review_on: '' };
