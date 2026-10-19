'use client';

import { Inbox } from 'lucide-react';

import { useGetStatus } from '@/api-client/generated/ai-provider/ai-provider';
import { useListProposals } from '@/api-client/generated/proposals/proposals';
import { cn } from '@/lib/utils';

import { NAV_ITEMS, SETTINGS_ITEM } from './nav-items';
import { NavLink } from './nav-link';

export function SideBar({ onNavigate }: { onNavigate?: () => void }) {
  const pending = useListProposals({ status: 'pending' }).data?.length ?? 0;
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
      {pending > 0 && (
        <div className='mt-3'>
          <NavLink href='/approvals' onNavigate={onNavigate}>
            <Inbox className='size-4 shrink-0' aria-hidden />
            <span className='flex-1'>승인 대기</span>
            <span className='rounded-full bg-warning-soft px-1.5 text-2xs font-semibold text-warning'>
              {pending}
              <span className='sr-only'>건</span>
            </span>
          </NavLink>
        </div>
      )}
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
