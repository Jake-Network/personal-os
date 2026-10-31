'use client';

import { Inbox } from 'lucide-react';

import { useGetStatus } from '@/api-client/generated/ai-provider/ai-provider';
import { useReviewCounts } from '@/features/review/review-view';
import { cn } from '@/lib/utils';

import { NAV_ITEMS, SETTINGS_ITEM } from './nav-items';
import { NavLink } from './nav-link';

export function SideBar({ onNavigate }: { onNavigate?: () => void }) {
  // Local-only counts: approvals, due decision reviews and unread notifications share one entry.
  const review = useReviewCounts();
  const provider = useGetStatus().data;
  const providerOn = provider?.connected && provider.plan_usage_enabled;
  const providerOff = provider?.status === 'needs_reauth';
  const providerText = providerOn ? 'AI 연결됨' : providerOff ? 'AI 다시 로그인 필요' : 'AI 연결 안 됨';
  const SettingsIcon = SETTINGS_ITEM.icon;

  return (
    <nav aria-label='주 메뉴' className='flex h-full flex-col gap-0.5 overflow-y-auto bg-card px-2.5 py-4'>
      <div className='px-2.5 pb-4 pt-1 text-title font-bold tracking-tight'>Personal OS</div>
      {NAV_ITEMS.map(item => (
        <NavLink key={item.href} href={item.href} end={item.end} onNavigate={onNavigate}>
          <item.icon className='size-4 shrink-0' aria-hidden />
          {item.label}
        </NavLink>
      ))}
      <div className='mt-3'>
        <NavLink href='/review' onNavigate={onNavigate}>
          <Inbox className='size-4 shrink-0' aria-hidden />
          <span className='flex-1'>검토함</span>
          {review.total > 0 && (
            <span
              className={cn(
                'rounded-full px-1.5 text-2xs font-semibold',
                review.approvals > 0 ? 'bg-warning-soft text-warning' : 'bg-accent text-accent-foreground',
              )}>
              {review.total}
              <span className='sr-only'>건 확인 필요</span>
            </span>
          )}
        </NavLink>
      </div>
      <div className='mt-auto pt-4'>
        <NavLink href={SETTINGS_ITEM.href} onNavigate={onNavigate}>
          <SettingsIcon className='size-4 shrink-0' aria-hidden />
          <span className='flex-1'>{SETTINGS_ITEM.label}</span>
          <span
            className={cn('size-2 rounded-full bg-input', providerOn && 'bg-primary', providerOff && 'bg-destructive')}
            title={providerText}
            aria-hidden
          />
          <span className='sr-only'>{providerText}</span>
        </NavLink>
      </div>
    </nav>
  );
}
