import type { Metadata } from 'next';

import { ApplicationsView } from '@/features/career/applications-view';
import { parseRecordParam } from '@/features/personal-data/utils/record-param';

export const metadata: Metadata = { title: '지원 현황' };

export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const { record } = await searchParams;
  return <ApplicationsView recordId={parseRecordParam(record)} />;
}
