import type { Metadata } from 'next';

import { TasksView } from '@/features/plan/tasks-view';
import { parseRecordParam } from '@/features/personal-data/utils/record-param';

export const metadata: Metadata = { title: '할 일' };

export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const { record } = await searchParams;
  return <TasksView recordId={parseRecordParam(record)} />;
}
