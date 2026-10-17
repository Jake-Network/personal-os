import { describe, expect, it } from 'vitest';

import { initialValues, toPayload } from './form-values';
import { type OpenApiSpec, schemaFields } from './schema-fields';

const spec: OpenApiSpec = {
  paths: {
    '/api/data/accounts': { post: { requestBody: { content: { 'application/json': { schema: { $ref: '#/components/schemas/AccountCreate' } } } } } },
  },
  components: {
    schemas: {
      AccountCreate: {
        required: ['name', 'kind'],
        properties: {
          name: { type: 'string' },
          kind: { enum: ['checking', 'savings'] },
          balance: { anyOf: [{ type: 'number' }, { type: 'string' }], default: '0' },
          balance_as_of: { anyOf: [{ type: 'string', format: 'date-time' }, { type: 'null' }] },
          is_liquid: { type: 'boolean', default: true },
          notes: { anyOf: [{ type: 'string' }, { type: 'null' }] },
        },
      },
    },
  },
};

describe('schemaFields', () => {
  it('maps pydantic schemas to form fields', () => {
    expect(schemaFields(spec, 'accounts').map(f => [f.name, f.kind, f.required, f.nullable])).toEqual([
      ['name', 'text', true, false],
      ['kind', 'enum', true, false],
      ['balance', 'decimal', false, false],
      ['balance_as_of', 'datetime', false, true],
      ['is_liquid', 'boolean', false, false],
      ['notes', 'longtext', false, true],
    ]);
  });

  it('rejects unknown resources', () => {
    expect(() => schemaFields(spec, 'nope')).toThrow('알 수 없는 리소스');
  });
});

describe('form values', () => {
  const fields = schemaFields(spec, 'accounts');

  it('fills defaults and round-trips to a payload', () => {
    const values = initialValues(fields);
    expect(values).toMatchObject({ balance: '0', is_liquid: true, notes: '' });
    expect(toPayload(fields, { ...values, name: ' 월급통장 ', kind: 'checking' })).toEqual({
      name: '월급통장',
      kind: 'checking',
      balance: '0', // decimals stay strings
      balance_as_of: null,
      is_liquid: true,
      notes: null,
    });
  });
});
