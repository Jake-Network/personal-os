import type { Metadata } from 'next';
import { JobsView } from '@/features/reviews/jobs-view';

export const metadata: Metadata = { title: '백그라운드 작업' };
export default function JobsPage() { return <JobsView />; }
