'use client';

import { TriangleAlert } from 'lucide-react';

import { EmptyState } from '@/components/empty-state';
import { Button } from '@/components/ui/button';

/** A screen that failed to render. The app shell stays, and the screen can be loaded again. */
export default function MainError({ retry }: { retry: () => void }) {
  return (
    <EmptyState icon={TriangleAlert} title='화면을 표시하지 못했습니다' className='py-24' action={<Button onClick={() => retry()}>다시 시도</Button>}>
      같은 문제가 반복되면 페이지를 새로 고쳐 주세요.
    </EmptyState>
  );
}
