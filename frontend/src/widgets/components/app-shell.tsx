'use client';

import { type ReactNode, useState } from 'react';

import { Menu } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet';

import { SideBar } from './side-bar';

export function AppShell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);

  return (
    <div className='grid h-full grid-cols-1 grid-rows-[auto_minmax(0,1fr)] md:grid-cols-[216px_minmax(0,1fr)] md:grid-rows-1'>
      <div className='flex items-center gap-2.5 border-b bg-card px-4 py-2.5 font-bold md:hidden'>
        <Button size='icon' onClick={() => setOpen(true)} aria-label='메뉴'>
          <Menu />
        </Button>
        Personal OS
      </div>
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
    </div>
  );
}
