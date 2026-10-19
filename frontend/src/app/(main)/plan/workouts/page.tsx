import type { Metadata } from 'next';

import { WorkoutsView } from '@/features/plan/workouts-view';
import { parseRecordParam } from '@/features/personal-data/utils/record-param';

export const metadata: Metadata = { title: '운동' };

export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const { record } = await searchParams;
  return <WorkoutsView recordId={parseRecordParam(record)} />;
}
