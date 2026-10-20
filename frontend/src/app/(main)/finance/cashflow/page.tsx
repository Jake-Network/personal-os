import type { Metadata } from 'next';

import { CashflowView } from '@/features/finance/cashflow-view';
import { parseRecordParam } from '@/features/personal-data/utils/record-param';

export const metadata: Metadata = { title: '장부' };

export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const { record, source } = await searchParams;
  const recordId = parseRecordParam(record);
  const origin = typeof source === 'string' ? source : 'cashflow_entries';
  return <CashflowView key={`${origin}:${recordId ?? ''}`} recordId={recordId} source={origin} />;
}
