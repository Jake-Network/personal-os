import type { ReactNode } from 'react';

import { cn } from '@/lib/utils';

import { PageContainer } from './page-container';
import { type PageTab, PageTabs } from './page-tabs';

/** An area of the app: its title, its sub-screens as tabs, then the active screen. */
export function AreaLayout({ title, tabs, children }: { title: string; tabs: PageTab[]; children: ReactNode }) {
  return (
    <PageContainer>
      <h1 className='mb-2 text-xl font-bold tracking-tight'>{title}</h1>
      <PageTabs tabs={tabs} />
      {children}
    </PageContainer>
  );
}

/** Actions row at the top of a tab screen. */
export function TabToolbar({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn('mb-4 flex flex-wrap items-center gap-2', className)}>{children}</div>;
}
