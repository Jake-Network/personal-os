import type { Metadata } from 'next';

import { CriteriaView } from '@/features/career/criteria-view';
import { parseRecordParam } from '@/features/personal-data/utils/record-param';

export const metadata: Metadata = { title: '평가 기준' };

export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const { record } = await searchParams;
  return <CriteriaView recordId={parseRecordParam(record)} />;
}
