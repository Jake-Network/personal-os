'use client';

import { Badge } from '@/components/ui/badge';

import { useGetStatus } from '@/api-client/generated/ai-provider/ai-provider';
import { useListProposals } from '@/api-client/generated/proposals/proposals';
import { cn } from '@/lib/utils';

import { RESOURCES } from '@/features/personal-data/consts/resources';

import { NavLink } from './nav-link';

const GROUPS = [...new Set(RESOURCES.map(r => r.group))];

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <div className='px-2.5 pb-1 pt-3.5 text-[11px] font-semibold text-faint'>{children}</div>;
}

export function SideBar({ onNavigate }: { onNavigate?: () => void }) {
  const pending = useListProposals({ status: 'pending' }).data?.length ?? 0;
  const provider = useGetStatus().data;
  const providerOn = provider?.connected && provider.plan_usage_enabled;
  const providerOff = provider?.status === 'needs_reauth';

  return (
    <nav className='flex h-full flex-col gap-0.5 overflow-y-auto bg-card px-2.5 py-4'>
      <div className='px-2.5 pb-3.5 pt-1 text-[15px] font-bold tracking-tight'>
        Personal OS
        <small className='block text-xs font-normal text-faint'>나의 실제 상황을 아는 AI 상담</small>
      </div>
      <NavLink href='/' end onNavigate={onNavigate}>
        대시보드
      </NavLink>
      <NavLink href='/advisor' onNavigate={onNavigate}>
        AI 상담
      </NavLink>
      <NavLink href='/approvals' onNavigate={onNavigate}>
        승인 대기 {pending > 0 && <Badge variant='warning'>{pending}</Badge>}
      </NavLink>
      <NavLink href='/memory' onNavigate={onNavigate}>
        기억 · 의사결정
      </NavLink>
      <NavLink href='/documents' onNavigate={onNavigate}>
        문서함
      </NavLink>
      <SectionLabel>자산</SectionLabel>
      <NavLink href='/finance' end onNavigate={onNavigate}>
        포트폴리오
      </NavLink>
      <NavLink href='/finance/history' onNavigate={onNavigate}>
        월별 순자산 기록
      </NavLink>

      <SectionLabel>데이터</SectionLabel>
      {GROUPS.map(g =>
        RESOURCES.filter(r => r.group === g).map(r => (
          <NavLink key={r.name} href={`/data/${r.name}`} onNavigate={onNavigate}>
            <span>{r.label}</span>
            <span className='text-xs text-faint'>{g}</span>
          </NavLink>
        )),
      )}

      <SectionLabel>설정</SectionLabel>
      <NavLink href='/settings/ai-provider' onNavigate={onNavigate}>
        <span>AI Provider</span>
        <span
          className={cn('size-2 rounded-full bg-input', providerOn && 'bg-primary', providerOff && 'bg-destructive')}
          title={provider?.connected ? '연결됨' : '연결 안 됨'}
        />
      </NavLink>
      <NavLink href='/settings/privacy' onNavigate={onNavigate}>
        데이터 공유
      </NavLink>
    </nav>
  );
}
