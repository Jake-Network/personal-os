import type { Metadata } from 'next';

import { ReviewsView } from '@/features/reviews/reviews-view';

export const metadata: Metadata = { title: '기간 회고' };

export default function Page() {
  return <ReviewsView />;
}
