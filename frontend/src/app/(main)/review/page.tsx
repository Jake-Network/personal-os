import type { Metadata } from 'next';

import { REVIEW_FILTERS, type ReviewFilter } from '@/features/review/filters';
import { ReviewView } from '@/features/review/review-view';

export const metadata: Metadata = { title: '검토함' };

export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  const { view } = await searchParams;
  const filter = REVIEW_FILTERS.includes(view as ReviewFilter) ? (view as ReviewFilter) : 'all';
  return <ReviewView filter={filter} />;
}
