import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { readDataOperations } from '../data-operations';
import { DataOperationResults } from './data-operation-results';

const pending = { operation: 'create', resource: 'holdings', status: 'needs_input', message: '수량을 확인해 주세요.' };

describe('named operation receipts', () => {
  it('distinguishes holdings in a batch and leaves old receipts readable', () => {
    const html = renderToStaticMarkup(createElement(DataOperationResults, {
      operations: readDataOperations([{ ...pending, target_label: 'TEST' }, { ...pending, target_label: 'MOCK' }, pending]),
    }));
    expect(html).toContain('보유 종목 · TEST');
    expect(html).toContain('보유 종목 · MOCK');
    expect(html).toContain('확인 필요');
  });

  it('ignores malformed optional labels without discarding a receipt or crashing', () => {
    const operations = readDataOperations([{ ...pending, target_label: { bad: true } }]);
    expect(operations).toHaveLength(1);
    expect(operations[0].target_label).toBeUndefined();
    expect(() => renderToStaticMarkup(createElement(DataOperationResults, { operations }))).not.toThrow();
  });
});
