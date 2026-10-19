import type { Metadata } from 'next';

import { TransactionsView } from '@/features/finance/transactions-view';
import { parseRecordParam } from '@/features/personal-data/utils/record-param';

export const metadata: Metadata = { title: '거래' };

export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const { record } = await searchParams;
  return <TransactionsView recordId={parseRecordParam(record)} />;
}
