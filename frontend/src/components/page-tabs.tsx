'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';

import { cn } from '@/lib/utils';

export interface PageTab {
  href: string;
  label: string;
  /** Match the path exactly instead of as a prefix (for an area's index tab). */
  end?: boolean;
}

/** Route-backed tabs for the screens inside one area. */
export function PageTabs({ tabs, className }: { tabs: PageTab[]; className?: string }) {
  const pathname = usePathname();
  return (
    <nav aria-label='하위 화면' className={cn('-mx-4 mb-5 overflow-x-auto border-b px-4 md:mx-0 md:px-0', className)}>
      <ul className='flex gap-1'>
        {tabs.map(t => {
          const active = t.end ? pathname === t.href : pathname === t.href || pathname.startsWith(`${t.href}/`);
          return (
            <li key={t.href}>
              <Link
                href={t.href}
                aria-current={active ? 'page' : undefined}
                className={cn(
                  '-mb-px inline-flex h-9 items-center whitespace-nowrap border-b-2 border-transparent px-3 text-ui text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                  active && 'border-primary font-semibold text-foreground',
                )}>
                {t.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
