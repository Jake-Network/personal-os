import type { Metadata } from 'next';
import { redirect } from 'next/navigation';

import { parseRecordParam } from '@/features/personal-data/utils/record-param';

export const metadata: Metadata = { title: '거래' };

export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const { record, source } = await searchParams;
  const recordId = parseRecordParam(record);
  const origin = typeof source === 'string' && ['financial_transactions', 'planned_expenses'].includes(source) ? source : 'cashflow_entries';
  redirect(`/finance/cashflow?source=${origin}${recordId !== null ? `&record=${recordId}` : ''}`);
}
