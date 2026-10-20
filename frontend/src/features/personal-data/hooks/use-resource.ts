import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { getSummaryQueryKey } from '@/api-client/generated/dashboard/dashboard';

import { RESOURCE_API, type Row } from '../api/resource-api';

export function useResourceRows<T extends Row = Row>(resource: string, enabled = true) {
  const api = RESOURCE_API[resource];
  return useQuery({
    queryKey: api?.queryKey ?? ['unknown', resource],
    queryFn: () => api.list() as Promise<T[]>,
    enabled: !!api && enabled,
  });
}

/** Everything that summarizes personal records is refreshed after a write. */
export function useInvalidateResource() {
  const queryClient = useQueryClient();
  return (resource: string) =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: RESOURCE_API[resource].queryKey }),
      queryClient.invalidateQueries({ queryKey: ['finance'] }),
      queryClient.invalidateQueries({ queryKey: getSummaryQueryKey() }),
      queryClient.invalidateQueries({ queryKey: ['/api/timeline'] }),
    ]);
}

/** Full-row update of a record, keeping every field the caller did not change. */
export function useUpdateRow(resource: string) {
  const invalidate = useInvalidateResource();
  const api = RESOURCE_API[resource];
  return useMutation({
    mutationFn: ({ row, changes }: { row: Row; changes: Record<string, unknown> }) => api.update(row.id, updatePayload(row, changes)),
    onSettled: () => invalidate(resource),
  });
}

const SERVER_FIELDS = new Set(['id', 'created_at', 'updated_at', 'ref', 'version', 'balance_stale']);

/** PUT replaces the record: send the stored fields plus the changes, never the server-managed ones. */
export function updatePayload(row: Row, changes: Record<string, unknown>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(row)) if (!SERVER_FIELDS.has(k)) out[k] = v;
  return { ...out, ...changes };
}
