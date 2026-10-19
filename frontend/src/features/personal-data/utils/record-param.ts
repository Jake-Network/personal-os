// Plain helpers (no 'use client'): server pages call parseRecordParam to read `?record=`.

export function parseRecordParam(value: string | string[] | undefined): number | null {
  const raw = Array.isArray(value) ? value[0] : value;
  return raw && /^\d+$/.test(raw) ? Number(raw) : null;
}

export function recordHref(path: string, id: number | string): string {
  return `${path}?record=${id}`;
}
