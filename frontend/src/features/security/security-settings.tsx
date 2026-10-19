'use client';

import { useQuery } from '@tanstack/react-query';
import { RefreshCw } from 'lucide-react';

import { customInstance } from '@/api-client/custom-client';
import { Section } from '@/components/page-container';
import { QueryStatus } from '@/components/query-status';
import { Badge, type BadgeProps } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';

type Diagnostics = {
  environment: string;
  checks: { id: string; state: 'verified' | 'unverified' | 'action_needed'; summary: string }[];
  lock_scope: string;
};
const STATE: Record<Diagnostics['checks'][number]['state'], { label: string; tone: NonNullable<BadgeProps['variant']> }> = {
  verified: { label: '확인됨', tone: 'success' },
  unverified: { label: '확인 못 함', tone: 'default' },
  action_needed: { label: '조치 필요', tone: 'warning' },
};
const CHECK_LABEL: Record<string, string> = { storage_encryption: '저장 공간 암호화', firewall: '방화벽' };

export function SecuritySettings() {
  const diagnostics = useQuery({
    queryKey: ['security-diagnostics'],
    queryFn: ({ signal }) => customInstance<Diagnostics>({ url: '/api/security/diagnostics', signal }),
    staleTime: 0,
  });
  return (
    <div className='max-w-[760px]'>
      <Section title='앱 잠금'>
        <div className='flex flex-col gap-1 py-2'>
          <p>15분 동안 아무 활동이 없으면 잠깁니다. 화면의 전체 잠금으로 모든 탭을 바로 잠글 수 있습니다.</p>
          <p className='text-ui text-muted-foreground'>{diagnostics.data?.lock_scope ?? '잠겨 있어도 허용한 자동 작업은 계속 실행됩니다.'}</p>
        </div>
      </Section>

      <Section
        title='저장 환경'
        info={<p>이 확인은 운영체제 설정을 바꾸지 않습니다. Windows에서는 WSL과 Docker 데이터가 실제로 저장되는 디스크도 확인하세요.</p>}
        actions={
          <Button size='sm' variant='ghost' disabled={diagnostics.isFetching} onClick={() => void diagnostics.refetch()}>
            <RefreshCw /> 다시 확인
          </Button>
        }>
        <QueryStatus pending={diagnostics.isPending} error={diagnostics.error} retry={diagnostics.refetch} label='저장 환경' rows={2} />
        <ul className='divide-y'>
          {diagnostics.data?.checks.map(check => (
            <li key={check.id} className='flex flex-col gap-0.5 py-2.5'>
              <span className='flex items-center gap-2'>
                <span className='font-medium'>{CHECK_LABEL[check.id] ?? '환경 점검'}</span>
                <Badge variant={STATE[check.state].tone}>{STATE[check.state].label}</Badge>
              </span>
              <span className='text-ui text-muted-foreground'>{check.summary}</span>
            </li>
          ))}
        </ul>
      </Section>

      <Section title='암호화 백업과 복원 검사'>
        <div className='flex flex-col gap-2 py-2'>
          <p>앱을 멈춘 뒤 데이터베이스·문서·키·설정을 한 번에 암호화해 이 컴퓨터에 백업합니다. 백업 비밀번호는 백업과 다른 곳에 보관하세요.</p>
          <p className='text-ui text-muted-foreground'>복원 검사는 따로 만든 임시 공간에서만 하며, 지금 쓰는 데이터를 덮어쓰지 않습니다.</p>
          <details className='text-ui'>
            <summary className='cursor-pointer text-muted-foreground'>고급: 실행 방법</summary>
            <p className='mt-2 text-muted-foreground'>
              터미널에서 <code className='rounded-sm bg-muted px-1 font-mono text-xs'>uv run python scripts/local_backup.py --help</code>를 실행하고, README의 백업 절차를 따르세요.
              restic이 필요하며, 임시 작업 폴더는 암호화된 저장 공간에 두세요.
            </p>
          </details>
        </div>
      </Section>
    </div>
  );
}
