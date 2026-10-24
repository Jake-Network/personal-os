import { expect, it } from 'vitest';

import { completeSlash, slashSuggestions } from './slash';

const playbooks = [
  { slug: '이직-점검', title: '이직 준비 점검', summary: '' },
  { slug: 'month-end', title: '월말 점검', summary: '' },
];

it('suggests playbooks only while the first word is being typed', () => {
  expect(slashSuggestions('/', playbooks).map(p => p.slug)).toEqual(['이직-점검', 'month-end']);
  expect(slashSuggestions('/이직', playbooks).map(p => p.slug)).toEqual(['이직-점검']);
  expect(slashSuggestions('/월말', playbooks).map(p => p.slug)).toEqual(['month-end']);
  expect(slashSuggestions('/이직-점검 질문', playbooks)).toEqual([]);
  expect(slashSuggestions('이직 /', playbooks)).toEqual([]);
});

it('completes with a trailing space so the question follows', () => {
  expect(completeSlash('이직-점검')).toBe('/이직-점검 ');
});
