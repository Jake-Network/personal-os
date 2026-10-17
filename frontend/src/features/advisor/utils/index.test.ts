import { describe, expect, it } from 'vitest';

import type { Category, SnapshotResponse } from '@/api-client/model';

import type { InspectorData } from '../types';
import { optionsFor, snapshotToInspector, stripBlocks } from './index';

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

describe('snapshotToInspector document evidence', () => {
  it('uses the exact captured version and excerpt for historical answers', () => {
    const citation = {
      ref: 'document_chunks:12',
      document_id: 1,
      version_id: 2,
      title: '이력서 v1',
      filename: 'resume.md',
      page: null,
      section: '경력',
      text: '당시 저장된 경력',
      as_of: '2026-01-01',
    };
    const snapshot = {
      context_snapshot_id: 'old',
      context_categories: ['career'],
      excluded_categories: [],
      source_updated_at: {},
      record_references: [],
      data_quality_flags: [],
      payload: { data: { search_documents: { citations: [citation] } } },
    } as unknown as SnapshotResponse;
    expect(snapshotToInspector(snapshot).document_citations).toEqual([citation]);
  });

  it('handles legacy snapshots and snapshots with purged evidence', () => {
    const snapshot = { payload: { data: {} } } as unknown as SnapshotResponse;
    expect(snapshotToInspector(snapshot).document_citations).toEqual([]);
  });
});
