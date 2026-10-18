import type { Metadata } from 'next';
import { ReviewsView } from '@/features/reviews/reviews-view';

export const metadata: Metadata = { title: '결정과 회고' };

export default function ReviewsPage() {
  return <ReviewsView />;
}
