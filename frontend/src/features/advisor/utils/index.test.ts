import { describe, expect, it } from 'vitest';

import type { Category, SnapshotResponse } from '@/api-client/model';

import type { InspectorData } from '../types';
import { optionsFor, publicWebUrl, sameRunIntent, snapshotToInspector, stripBlocks } from './index';

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
      exclude: ['goals'],
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

describe('web evidence', () => {
  it('retains the captured web excerpt and hash for historical answers', () => {
    const source = {
      ref: 'web:1',
      url: 'https://example.com/job',
      title: '채용',
      published_at: null,
      retrieved_at: '2026-10-18T00:00:00Z',
      excerpts: ['당시 채용 조건'],
      content_hash: 'captured-hash',
    };
    const snapshot = { payload: { data: { web_search: { pages: [source] } } } } as unknown as SnapshotResponse;
    expect(snapshotToInspector(snapshot).web_sources).toEqual([source]);
    expect(snapshotToInspector({ payload: {} } as SnapshotResponse).web_sources).toEqual([]);
  });

  it('only makes HTTP(S) source links clickable without embedded credentials', () => {
    expect(publicWebUrl('https://example.com/job')).toBe('https://example.com/job');
    for (const url of ['javascript:alert(1)', 'data:text/html,hello', 'file:///etc/passwd', '//example.com', 'https://user:password@example.com']) {
      expect(publicWebUrl(url)).toBeNull();
    }
  });
});

describe('sameRunIntent', () => {
  const original = {
    message: '생활비는?',
    request_id: 'first',
    exclude: ['financial'],
    document_ids: [2],
    document_search: true,
    depth: 'auto',
    parent_revision: 1,
  };
  it('keeps retry identity when only transport identity and observed revision change', () => {
    expect(sameRunIntent(original, { ...original, request_id: 'second', parent_revision: 2 })).toBe(true);
  });
  it.each([
    { exclude: [] },
    { categories: ['career'] },
    { document_ids: [3] },
    { document_search: false },
    { depth: 'deep' },
    { web_search: true, web_query: '공개 정보' },
    { history_company: '회사' },
    { scenario_id: 'other' },
  ])('never reuses a body after changing request controls: %j', change => {
    expect(sameRunIntent(original, { ...original, ...change })).toBe(false);
  });
});
