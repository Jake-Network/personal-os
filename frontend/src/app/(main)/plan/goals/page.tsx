import type { Metadata } from 'next';

import { GoalsView } from '@/features/plan/goals-view';
import { parseRecordParam } from '@/features/personal-data/utils/record-param';

export const metadata: Metadata = { title: '목표' };

export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const { record } = await searchParams;
  return <GoalsView recordId={parseRecordParam(record)} />;
}
