import type { Metadata } from 'next';

import { DecisionJournal } from '@/features/memory/components/decision-journal';
import { parseRecordParam } from '@/features/personal-data/utils/record-param';

export const metadata: Metadata = { title: '결정 기록' };

export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const { record } = await searchParams;
  return <DecisionJournal recordId={parseRecordParam(record)} />;
}
