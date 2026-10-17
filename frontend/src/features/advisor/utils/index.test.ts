import { describe, expect, it } from 'vitest';

import type { Category } from '@/api-client/model';

import type { InspectorData } from '../types';
import { optionsFor, stripBlocks } from './index';

const base = {
  route: { requested: ['financial', 'goals'], selected: ['financial', 'goals'], excluded: [], matched_terms: [], reason: 'keyword' },
} as unknown as InspectorData;

describe('optionsFor', () => {
  it('only excludes when nothing is forced on', () => {
    expect(optionsFor(base, new Set(), new Set<Category>(['goals']))).toEqual({ exclude: ['goals'] });
  });

  it('switches to an explicit category list when something is forced on', () => {
    expect(optionsFor(base, new Set<Category>(['career']), new Set<Category>(['goals']))).toEqual({
      categories: ['financial', 'career'],
      exclude: [],
    });
  });
});

describe('stripBlocks', () => {
  it('removes finished and still-streaming proposal blocks', () => {
    expect(stripBlocks('답변\n```proposal\n{"a":1}\n```\n끝')).toBe('답변\n\n끝');
    expect(stripBlocks('답변\n```memory\n{"kind":')).toBe('답변');
  });
});
