import type { Metadata } from 'next';

import { AccountsView } from '@/features/finance/accounts-view';
import { parseRecordParam } from '@/features/personal-data/utils/record-param';

export const metadata: Metadata = { title: '계좌·부채' };

export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const { record } = await searchParams;
  return <AccountsView recordId={parseRecordParam(record)} />;
}
