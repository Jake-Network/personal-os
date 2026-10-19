import type { Metadata } from 'next';

import { EventsView } from '@/features/plan/events-view';
import { parseRecordParam } from '@/features/personal-data/utils/record-param';

export const metadata: Metadata = { title: '일정' };

export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const { record } = await searchParams;
  return <EventsView recordId={parseRecordParam(record)} />;
}
