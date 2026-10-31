'use client';

import { useState } from 'react';

import Link from 'next/link';

import { useQueryClient } from '@tanstack/react-query';
import { CheckCircle2, Circle } from 'lucide-react';

import { getOnboardingQueryKey, useOnboarding, useSaveOnboarding } from '@/api-client/generated/dashboard/dashboard';
import type { DashboardChecklist } from '@/api-client/model';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { BalanceCheckInSheet } from '@/features/finance/balance-check-in';
import { CashflowImportDialog } from '@/features/finance/cashflow-import-dialog';
import { ConnectionTest } from '@/features/settings/components/connection-test';
import { cn } from '@/lib/utils';

const STARTERS: [string, string][] = [
  ['runway', '지금 쉬면 몇 개월 버틸 수 있을까?'],
  ['week', '이번 주 무엇부터 할까?'],
  ['expenses', '이번 달 지출 괜찮을까?'],
];

function Step({ done, title, children }: { done: boolean; title: string; children: React.ReactNode }) {
  return (
    <li className='flex gap-3 py-3'>
      {done ? <CheckCircle2 className='mt-0.5 size-4 shrink-0 text-success' aria-hidden /> : <Circle className='mt-0.5 size-4 shrink-0 text-faint' aria-hidden />}
      <div className='flex min-w-0 flex-1 flex-col gap-2'>
        <span className={cn('font-medium', done && 'text-muted-foreground')}>
          {title}
          <span className='sr-only'>{done ? ' 완료' : ' 준비 필요'}</span>
        </span>
        {children}
      </div>
    </li>
  );
}

/** First-run guide: four short setup steps and a first question. Opens once; it can be reopened from the home checklist. */
export function OnboardingGuide({ checklist, open, onOpenChange }: { checklist: DashboardChecklist; open?: boolean; onOpenChange?: (open: boolean) => void }) {
  const client = useQueryClient();
  const state = useOnboarding();
  const save = useSaveOnboarding();
  const [checkingIn, setCheckingIn] = useState(false);
  const [importing, setImporting] = useState(false);
  const incomplete = !Object.values(checklist).every(Boolean);
  const visible = open ?? (state.isSuccess && !state.data.dismissed && incomplete);
  const dismiss = () => {
    onOpenChange?.(false);
    if (state.data?.dismissed) return;
    save.mutate({ data: { dismissed: true } }, { onSuccess: data => client.setQueryData(getOnboardingQueryKey(), data) });
  };

  return (
    <>
      <Dialog open={visible && !checkingIn && !importing} onOpenChange={next => !next && dismiss()}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>5분 시작 가이드</DialogTitle>
            <DialogDescription>몇 가지만 기록하면 상담이 내 상황에 맞춰 답합니다. 건너뛰어도 나중에 홈의 체크리스트에서 이어 할 수 있습니다.</DialogDescription>
          </DialogHeader>
          <ol className='divide-y text-ui'>
            <Step done={checklist.ai_configuration_complete} title='1. AI 연결'>
              <div className='flex flex-wrap items-center gap-2'>
                <Button asChild size='sm'>
                  <Link href='/settings/ai-provider'>연결 설정</Link>
                </Button>
                {checklist.ai_configuration_complete && <ConnectionTest />}
              </div>
            </Step>
            <Step done={checklist.has_cash_account} title='2. 생활비 통장 잔액'>
              <div className='flex flex-wrap gap-2'>
                {checklist.has_cash_account ? (
                  <Button size='sm' onClick={() => setCheckingIn(true)}>
                    잔고 업데이트
                  </Button>
                ) : (
                  <Button asChild size='sm'>
                    <Link href='/finance/accounts'>계좌 추가</Link>
                  </Button>
                )}
              </div>
            </Step>
            <Step done={checklist.has_recent_expense} title='3. 최근 지출'>
              <div className='flex flex-wrap gap-2'>
                <Button size='sm' onClick={() => setImporting(true)}>
                  은행·카드 내역 가져오기
                </Button>
                <Button asChild size='sm' variant='ghost'>
                  <Link href='/finance/cashflow'>직접 기록</Link>
                </Button>
              </div>
              <span className='text-xs text-faint'>버틸 수 있는 기간은 최근 3개월 지출이 모두 기록되어야 계산합니다.</span>
            </Step>
            <Step done={checklist.has_active_application_or_goal} title='4. 목표 또는 진행 중인 지원'>
              <div className='flex flex-wrap gap-2'>
                <Button asChild size='sm'>
                  <Link href='/plan/goals'>목표 추가</Link>
                </Button>
                <Button asChild size='sm' variant='ghost'>
                  <Link href='/career'>지원 현황 추가</Link>
                </Button>
              </div>
            </Step>
            <Step done={false} title='5. 첫 질문'>
              <div className='flex flex-wrap gap-2'>
                {STARTERS.map(([code, label]) => (
                  <Button key={code} asChild size='sm' variant='ghost' onClick={dismiss}>
                    <Link href={`/advisor?briefing=${code}`}>{label}</Link>
                  </Button>
                ))}
              </div>
              <span className='text-xs text-faint'>질문 초안만 채웁니다. 보내기 전에 고칠 수 있습니다. 기록이 부족하면 무엇이 부족한지 알려 줍니다.</span>
            </Step>
          </ol>
          <div className='mt-2 flex justify-end'>
            <Button onClick={dismiss}>나중에 할게요</Button>
          </div>
        </DialogContent>
      </Dialog>
      <BalanceCheckInSheet open={checkingIn} onOpenChange={setCheckingIn} />
      <CashflowImportDialog open={importing} onOpenChange={setImporting} />
    </>
  );
}
