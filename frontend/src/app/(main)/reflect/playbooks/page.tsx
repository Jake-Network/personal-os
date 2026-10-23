import type { Metadata } from 'next';

import { parseRecordParam } from '@/features/personal-data/utils/record-param';
import { PlaybooksView } from '@/features/playbooks/components/playbooks-view';

export const metadata: Metadata = { title: '플레이북' };

export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const { record } = await searchParams;
  return <PlaybooksView recordId={parseRecordParam(record)} />;
}
