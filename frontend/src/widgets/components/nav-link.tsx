'use client';

import type { ReactNode } from 'react';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

import { cn } from '@/lib/utils';

export function isActive(pathname: string, href: string, end?: boolean) {
  return end ? pathname === href : pathname === href || pathname.startsWith(`${href}/`);
}

/** Sidebar link with an active state; `end` matches the path exactly instead of as a prefix. */
export function NavLink({ href, end, onNavigate, children }: { href: string; end?: boolean; onNavigate?: () => void; children: ReactNode }) {
  const pathname = usePathname();
  const active = isActive(pathname, href, end);
  return (
    <Link
      href={href}
      onClick={onNavigate}
      aria-current={active ? 'page' : undefined}
      className={cn(
        'flex h-9 items-center gap-2.5 rounded-md px-2.5 text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
        active && 'bg-accent font-semibold text-accent-foreground hover:bg-accent hover:text-accent-foreground',
      )}>
      {children}
    </Link>
  );
}
