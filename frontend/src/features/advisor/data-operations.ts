import type { QueryClient } from '@tanstack/react-query';

import { getSummaryQueryKey } from '@/api-client/generated/dashboard/dashboard';
import { RESOURCE_API } from '@/features/personal-data/api/resource-api';
import { RESOURCES } from '@/features/personal-data/consts/resources';

import { evidenceHref } from './consts';

export interface DataOperation {
  operation: 'create' | 'read' | 'update' | 'delete';
  resource: string;
  status: 'saved' | 'read' | 'needs_input' | 'failed';
  record_id?: number;
  record_ref?: { table: string; id: number; updated_at?: string | null; category?: string };
  message: string;
}

export function readDataOperations(value: unknown): DataOperation[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is DataOperation =>
    item !== null && typeof item === 'object' &&
    ['create', 'read', 'update', 'delete'].includes(item.operation) &&
    ['saved', 'read', 'needs_input', 'failed'].includes(item.status) &&
    typeof item.resource === 'string' && typeof item.message === 'string',
  );
}

const MANAGEMENT_PATH: Record<string, string> = {
  accounts: '/finance/accounts',
  liabilities: '/finance/accounts',
  'other-assets': '/finance/accounts',
  holdings: '/finance/investments',
  'fx-rates': '/finance/investments',
  'cashflow-entries': '/finance/cashflow',
  'planned-expenses': '/finance/cashflow',
  'job-applications': '/career',
  interviews: '/career',
  'career-criteria': '/career/criteria',
  'calendar-events': '/plan/events',
  tasks: '/plan/tasks',
  goals: '/plan/goals',
  'workout-logs': '/plan/workouts',
};

export function dataOperationHref(operation: DataOperation): string | null {
  if (!['saved', 'read'].includes(operation.status)) return null;
  const path = MANAGEMENT_PATH[operation.resource];
  if (typeof path !== 'string') return null;
  return operation.operation === 'delete' ? path : evidenceHref(operation.resource.replaceAll('-', '_'), operation.record_id) ?? path;
}

/** Receipts, including recovered runs, refresh the same caches as direct user edits. */
export async function invalidateDataOperationQueries(client: QueryClient, operations: DataOperation[]): Promise<void> {
  const resources = new Set(operations.filter(op => op.status === 'saved' && op.operation !== 'read').map(op => op.resource));
  const known = [...resources].filter(resource => Object.hasOwn(RESOURCE_API, resource));
  if (!known.length) return;
  const keys: (readonly unknown[])[] = [getSummaryQueryKey(), ['/api/timeline']];
  known.forEach(resource => keys.push(RESOURCE_API[resource].queryKey));
  if (known.some(resource => RESOURCES.find(meta => meta.name === resource)?.financial)) keys.push(['finance']);
  await Promise.all(keys.map(queryKey => client.invalidateQueries({ queryKey })));
}
