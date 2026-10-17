import Link from 'next/link';

import { EmptyState } from '@/components/empty-state';

export default function NotFound() {
  return (
    <EmptyState className='py-24'>
      페이지를 찾을 수 없습니다.{' '}
      <Link href='/' className='text-primary hover:underline'>
        대시보드로
      </Link>
    </EmptyState>
  );
}
