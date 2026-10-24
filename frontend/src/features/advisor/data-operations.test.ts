import { QueryClient } from '@tanstack/react-query';
import { describe, expect, it } from 'vitest';

import { getSummaryQueryKey } from '@/api-client/generated/dashboard/dashboard';
import { getListAccountsQueryKey, getListWorkoutLogsQueryKey } from '@/api-client/generated/personal-data/personal-data';

import { dataOperationHref, invalidateDataOperationQueries, readDataOperations } from './data-operations';

const savedWorkout = { operation: 'create', resource: 'workout-logs', status: 'saved', record_id: 7, message: '운동을 기록했습니다.' };

describe('consultation data operations', () => {
  it('accepts saved receipts and excludes malformed or unknown states', () => {
    expect(readDataOperations([savedWorkout, { ...savedWorkout, status: 'pending' }, null, { resource: 'accounts' }])).toEqual([savedWorkout]);
    expect(readDataOperations(undefined)).toEqual([]);
  });

  it('links existing records to their editor and deleted records to their management page', () => {
    const [saved] = readDataOperations([savedWorkout]);
    expect(dataOperationHref(saved)).toBe('/plan/workouts?record=7');
    expect(dataOperationHref({ ...saved, operation: 'delete' })).toBe('/plan/workouts');
    expect(dataOperationHref({ ...saved, resource: 'holdings' })).toBe('/finance/investments');
    expect(dataOperationHref({ ...saved, status: 'failed' })).toBeNull();
    expect(dataOperationHref({ ...saved, resource: 'not-a-resource' })).toBeNull();
    const [withReference] = readDataOperations([{ ...savedWorkout, record_ref: { table: 'workout_logs', id: 7, category: 'health' } }]);
    expect(dataOperationHref(withReference)).toBe('/plan/workouts?record=7');
  });

  it('refreshes saved resources and their summaries without refetching unrelated records', async () => {
    const client = new QueryClient();
    const keys = [getListWorkoutLogsQueryKey(), getListAccountsQueryKey(), getSummaryQueryKey(), ['/api/timeline'], ['finance', 'holdings']];
    keys.forEach(key => client.setQueryData(key, ['synthetic']));
    await invalidateDataOperationQueries(client, readDataOperations([savedWorkout]));
    expect(client.getQueryState(getListWorkoutLogsQueryKey())?.isInvalidated).toBe(true);
    expect(client.getQueryState(getSummaryQueryKey())?.isInvalidated).toBe(true);
    expect(client.getQueryState(['/api/timeline'])?.isInvalidated).toBe(true);
    expect(client.getQueryState(getListAccountsQueryKey())?.isInvalidated).toBe(false);
    expect(client.getQueryState(['finance', 'holdings'])?.isInvalidated).toBe(false);
    await invalidateDataOperationQueries(client, readDataOperations([{ ...savedWorkout, resource: 'accounts' }]));
    expect(client.getQueryState(['finance', 'holdings'])?.isInvalidated).toBe(true);
    client.clear();
  });

  it('does not invalidate data for reads, failed writes or questions requiring clarification', async () => {
    const client = new QueryClient();
    client.setQueryData(getListWorkoutLogsQueryKey(), ['synthetic']);
    await invalidateDataOperationQueries(client, readDataOperations([
      { ...savedWorkout, operation: 'read', status: 'read' },
      { ...savedWorkout, status: 'failed' },
      { ...savedWorkout, status: 'needs_input' },
    ]));
    expect(client.getQueryState(getListWorkoutLogsQueryKey())?.isInvalidated).toBe(false);
    client.clear();
  });
});
