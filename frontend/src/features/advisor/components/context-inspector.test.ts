import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { readInspectorData } from '../utils';
import { ContextInspector } from './context-inspector';

describe('evidence while a data command is saved before its answer', () => {
  it.each(['running', 'failed'])('keeps the %s receipt separate from evidence that is not ready', status => {
    const run = { status, result: { data_operations: [{ resource: 'workout-logs', status: 'saved' }], context: {} } };
    expect(() => renderToStaticMarkup(createElement(ContextInspector, {
      data: readInspectorData(run.result.context) ?? null, mode: 'answer',
    }))).not.toThrow();
    expect(readInspectorData(run.result.context)).toBeUndefined();
    expect(run.result.data_operations[0].status).toBe('saved');
  });

  it('accepts completed evidence and rejects missing fields from REST or SSE', () => {
    const evidence = { context_snapshot_id: 'synthetic-snapshot', context_reused: false,
      categories: ['health'], excluded_categories: [], source_updated_at: {},
      record_references: [], data_quality_flags: [] };
    expect(readInspectorData(evidence)).toBe(evidence);
    for (const value of [undefined, null, {}, [], { categories: [] }, { ...evidence, categories: null },
      { ...evidence, record_references: null }, { ...evidence, data_quality_flags: null }]) {
      expect(readInspectorData(value)).toBeUndefined();
    }
  });
});
