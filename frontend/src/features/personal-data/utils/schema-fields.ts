/** Builds data-entry forms from the backend's pydantic schemas (via /openapi.json), so the two never drift. */

export type FieldKind = 'text' | 'longtext' | 'decimal' | 'integer' | 'duration' | 'boolean' | 'date' | 'datetime' | 'enum';

export interface FieldSpec {
  name: string;
  kind: FieldKind;
  required: boolean;
  nullable: boolean;
  options?: string[];
  defaultValue?: unknown;
}

interface JsonSchema {
  type?: string;
  format?: string;
  enum?: string[];
  anyOf?: JsonSchema[];
  default?: unknown;
  $ref?: string;
  properties?: Record<string, JsonSchema>;
  required?: string[];
}

export interface OpenApiSpec {
  paths?: Record<string, { post?: { requestBody?: { content?: Record<string, { schema?: JsonSchema }> } } }>;
  components: { schemas: Record<string, JsonSchema> };
}

const LONG_TEXT = new Set(['jd_text', 'notes', 'prep_notes', 'description', 'csv_text']);

function kindOf(name: string, variants: JsonSchema[]): Pick<FieldSpec, 'kind' | 'options'> {
  const enumVariant = variants.find(v => Array.isArray(v.enum));
  if (enumVariant) return { kind: 'enum', options: enumVariant.enum };
  const types = variants.map(v => v.type);
  const formats = variants.map(v => v.format);
  if (formats.includes('duration-seconds')) return { kind: 'duration' };
  if (formats.includes('date')) return { kind: 'date' };
  if (formats.includes('date-time')) return { kind: 'datetime' };
  if (types.includes('boolean')) return { kind: 'boolean' };
  if (types.includes('integer')) return { kind: 'integer' };
  if (types.includes('number')) return { kind: 'decimal' }; // pydantic Decimal = number | string
  return { kind: LONG_TEXT.has(name) ? 'longtext' : 'text' };
}

export function schemaFields(spec: OpenApiSpec, resource: string): FieldSpec[] {
  const ref = spec.paths?.[resource.startsWith('/') ? resource : `/api/data/${resource}`]?.post?.requestBody?.content?.['application/json']?.schema?.$ref;
  if (!ref) throw new Error(`알 수 없는 리소스: ${resource}`);
  const schema = spec.components.schemas[ref.split('/').pop()!];
  const required = new Set(schema.required ?? []);
  return Object.entries(schema.properties ?? {}).map(([name, prop]) => {
    const variants = prop.anyOf ?? [prop];
    const nonNull = variants.filter(v => v.type !== 'null');
    return {
      name,
      required: required.has(name),
      nullable: nonNull.length !== variants.length,
      defaultValue: prop.default,
      ...kindOf(name, nonNull),
    };
  });
}
