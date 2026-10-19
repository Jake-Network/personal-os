import type { Metadata } from 'next';

import { CashflowView } from '@/features/finance/cashflow-view';
import { parseRecordParam } from '@/features/personal-data/utils/record-param';

export const metadata: Metadata = { title: '가계부' };

export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const { record } = await searchParams;
  return <CashflowView recordId={parseRecordParam(record)} />;
}
