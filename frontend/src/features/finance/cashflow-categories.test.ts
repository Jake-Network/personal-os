import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

import { describe, expect, it } from 'vitest';

import { DataForm } from '@/features/personal-data/components/data-form';
import type { FieldSpec } from '@/features/personal-data/utils/schema-fields';

import { CASHFLOW_CATEGORIES, cashflowCategories } from './cashflow-categories';

const fields: FieldSpec[] = [
  { name: 'kind', kind: 'enum', options: ['income', 'expense'], required: true, nullable: false },
  { name: 'category', kind: 'text', required: false, nullable: true },
];

function form(kind: string, category = '') {
  return renderToStaticMarkup(createElement(DataForm, {
    fields,
    current: { kind, category },
    suggestions: { category: { dependsOn: 'kind', options: CASHFLOW_CATEGORIES } },
    submitLabel: '저장',
    onSubmit: async () => {},
    onCancel: () => {},
  }));
}

describe('cashflow category suggestions', () => {
  it('shows income suggestions in the income form', () => {
    const html = form('income');
    expect(html).toContain('<option value="급여">');
    expect(html).toContain('<option value="배당">');
    expect(html).not.toContain('<option value="식비">');
  });

  it('shows only expense suggestions in the expense form', () => {
    const html = form('expense', '반려동물');
    expect(html).toContain('<option value="식비">');
    expect(html).not.toContain('<option value="급여">');
  });

  it('filters the list suggestions by kind and shows both for all records', () => {
    expect(cashflowCategories('income')).toContain('급여');
    expect(cashflowCategories('income')).not.toContain('식비');
    expect(cashflowCategories('expense')).toContain('식비');
    expect(cashflowCategories('expense')).not.toContain('급여');
    expect(cashflowCategories('')).toEqual(expect.arrayContaining(['급여', '식비']));
  });
});
