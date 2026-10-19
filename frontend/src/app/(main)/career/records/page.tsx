import type { Metadata } from 'next';

import { CareerView } from '@/features/career/career-view';
import { parseRecordParam } from '@/features/personal-data/utils/record-param';

export const metadata: Metadata = { title: '경력 기록' };

export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const { record } = await searchParams;
  return <CareerView recordId={parseRecordParam(record)} />;
}
