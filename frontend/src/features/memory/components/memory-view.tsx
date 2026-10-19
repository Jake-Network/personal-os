'use client';

import { MemoryList } from './memory-list';

/** Long-term memories the advisor may use as your profile. */
export function MemoryView() {
  return (
    <div className='max-w-[860px]'>
      <MemoryList />
    </div>
  );
}
