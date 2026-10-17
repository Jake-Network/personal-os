/** Builds data-entry forms from the backend's pydantic schemas, so the two never drift. */

export type FieldKind = 'text' | 'longtext' | 'decimal' | 'integer' | 'boolean' | 'date' | 'datetime' | 'enum';

export interface FieldSpec {
  name: string;
  kind: FieldKind;
  required: boolean;
  nullable: boolean;
  options?: string[];
  defaultValue?: unknown;
}

let specPromise: Promise<any> | null = null;

function loadSpec(): Promise<any> {
  specPromise ??= fetch('/openapi.json').then((r) => {
    if (!r.ok) throw new Error('OpenAPI 스키마를 불러오지 못했습니다.');
    return r.json();
  });
  return specPromise;
}

const LONG_TEXT = new Set(['jd_text', 'notes', 'prep_notes', 'description']);

function kindOf(name: string, variants: any[]): Pick<FieldSpec, 'kind' | 'options'> {
  const enumVariant = variants.find((v) => Array.isArray(v.enum));
  if (enumVariant) return { kind: 'enum', options: enumVariant.enum };
  const types = variants.map((v) => v.type);
  const formats = variants.map((v) => v.format);
  if (formats.includes('date')) return { kind: 'date' };
  if (formats.includes('date-time')) return { kind: 'datetime' };
  if (types.includes('boolean')) return { kind: 'boolean' };
  if (types.includes('integer')) return { kind: 'integer' };
  if (types.includes('number')) return { kind: 'decimal' }; // pydantic Decimal = number | string
  return { kind: LONG_TEXT.has(name) ? 'longtext' : 'text' };
}

export async function createSchemaFields(resource: string): Promise<FieldSpec[]> {
  const spec = await loadSpec();
  const ref: string | undefined =
    spec.paths?.[`/api/data/${resource}`]?.post?.requestBody?.content?.['application/json']?.schema?.$ref;
  if (!ref) throw new Error(`알 수 없는 리소스: ${resource}`);
  const schema = spec.components.schemas[ref.split('/').pop()!];
  const required = new Set<string>(schema.required ?? []);
  return Object.entries<any>(schema.properties).map(([name, prop]) => {
    const variants: any[] = prop.anyOf ?? [prop];
    const nonNull = variants.filter((v) => v.type !== 'null');
    return {
      name,
      required: required.has(name),
      nullable: nonNull.length !== variants.length,
      defaultValue: prop.default,
      ...kindOf(name, nonNull),
    };
  });
}
