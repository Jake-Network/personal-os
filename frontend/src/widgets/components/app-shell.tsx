'use client';

import { type ReactNode, useState } from 'react';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

import { Menu } from 'lucide-react';

import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet';
import { cn } from '@/lib/utils';

import { MOBILE_TABS, NAV_ITEMS } from './nav-items';
import { isActive } from './nav-link';
import { SideBar } from './side-bar';

function MobileTabBar({ onMore }: { onMore: () => void }) {
  const pathname = usePathname();
  const tabs = NAV_ITEMS.filter(i => MOBILE_TABS.includes(i.href));
  const moreActive = !tabs.some(t => isActive(pathname, t.href, t.end));
  const cell = 'flex flex-1 flex-col items-center justify-center gap-0.5 py-1.5 text-2xs text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring';
  return (
    <nav aria-label='주 메뉴' className='flex border-t bg-card pb-[env(safe-area-inset-bottom)] md:hidden'>
      {tabs.map(t => {
        const active = isActive(pathname, t.href, t.end);
        return (
          <Link key={t.href} href={t.href} aria-current={active ? 'page' : undefined} className={cn(cell, active && 'font-semibold text-primary')}>
            <t.icon className='size-5' aria-hidden />
            {t.short ?? t.label}
          </Link>
        );
      })}
      <button type='button' onClick={onMore} className={cn(cell, moreActive && 'font-semibold text-primary')}>
        <Menu className='size-5' aria-hidden />
        더보기
      </button>
    </nav>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);

  return (
    <div className='grid h-full grid-cols-1 grid-rows-[minmax(0,1fr)_auto] md:grid-cols-[220px_minmax(0,1fr)] md:grid-rows-1'>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side='left' className='md:hidden'>
          <SheetTitle className='sr-only'>메뉴</SheetTitle>
          <SideBar onNavigate={() => setOpen(false)} />
        </SheetContent>
      </Sheet>
      <aside className='hidden border-r md:block'>
        <SideBar />
      </aside>
      <main className='min-w-0 overflow-y-auto'>{children}</main>
      <MobileTabBar onMore={() => setOpen(true)} />
    </div>
  );
}
