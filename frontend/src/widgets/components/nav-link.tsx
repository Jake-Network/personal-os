'use client';

import type { ReactNode } from 'react';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

import { cn } from '@/lib/utils';

/** Sidebar link with an active state; `end` matches the path exactly instead of as a prefix. */
export function NavLink({ href, end, onNavigate, children }: { href: string; end?: boolean; onNavigate?: () => void; children: ReactNode }) {
  const pathname = usePathname();
  const active = end ? pathname === href : pathname === href || pathname.startsWith(`${href}/`);
  return (
    <Link
      href={href}
      onClick={onNavigate}
      className={cn(
        'flex items-center justify-between rounded-sm px-2.5 py-1.5 text-muted-foreground hover:bg-muted',
        active && 'bg-accent font-semibold text-foreground hover:bg-accent',
      )}>
      {children}
    </Link>
  );
}
