'use client';

import { useQuery } from '@tanstack/react-query';
import { customInstance } from '@/api-client/custom-client';
import { errorMessage } from '@/api-client/api-error';
import { Button } from '@/components/ui/button';

type Diagnostics = {
  environment: string;
  checks: { id: string; state: 'verified' | 'unverified' | 'action_needed'; summary: string }[];
  lock_scope: string;
};
const stateLabels = { verified: '확인됨', unverified: '미확인', action_needed: '조치 필요' };
const checkLabels: Record<string, string> = { storage_encryption: '저장 암호화', firewall: '방화벽' };

export function SecuritySettings() {
  const diagnostics = useQuery({
    queryKey: ['security-diagnostics'],
    queryFn: ({ signal }) => customInstance<Diagnostics>({ url: '/api/security/diagnostics', signal }),
    staleTime: 0,
  });
  return (
    <div className='mx-auto max-w-3xl space-y-6 p-6'>
      <h1 className='text-2xl font-semibold'>보안과 로컬 백업</h1>
      <section className='space-y-3 rounded-xl border p-5'>
        <h2 className='font-semibold'>앱 잠금</h2>
        <p className='text-sm'>사용자 활동이 15분 동안 없으면 잠깁니다. 화면 오른쪽의 전체 잠금으로 모든 탭을 잠글 수 있습니다.</p>
        <p className='text-sm text-muted-foreground'>
          {diagnostics.data?.lock_scope ?? '앱 잠금 중에도 승인한 백그라운드 작업은 계속 데이터를 읽을 수 있습니다.'}
        </p>
      </section>
      <section className='space-y-4 rounded-xl border p-5'>
        <div className='flex items-center justify-between gap-3'>
          <h2 className='font-semibold'>저장 환경 확인</h2>
          <Button size='sm' disabled={diagnostics.isFetching} onClick={() => void diagnostics.refetch()}>
            다시 확인
          </Button>
        </div>
        {diagnostics.isPending && <p role='status'>환경을 확인하고 있습니다…</p>}
        {diagnostics.error && (
          <p role='alert' className='text-sm text-destructive'>
            {errorMessage(diagnostics.error)}
          </p>
        )}
        {diagnostics.data?.checks.map(check => (
          <div key={check.id} className='space-y-1'>
            <p className='text-sm font-medium'>
              {checkLabels[check.id] ?? check.id} · {stateLabels[check.state]}
            </p>
            <p className='text-sm text-muted-foreground'>{check.summary}</p>
          </div>
        ))}
        <p className='text-sm text-muted-foreground'>
          이 확인은 OS 설정을 변경하지 않습니다. Windows에서는 WSL과 Docker 데이터가 실제로 저장되는 디스크도 확인해야 합니다.
        </p>
      </section>
      <section className='space-y-3 rounded-xl border p-5'>
        <h2 className='font-semibold'>암호화 백업과 복원 검사</h2>
        <p className='text-sm'>
          앱과 worker를 중지한 뒤 로컬 restic 저장소에 DB·문서·키·설정을 함께 백업합니다. 평문 임시 작업 경로는 OS에서 암호화한 저장 영역을
          사용하세요.
        </p>
        <p className='text-sm'>
          복원 검사는 격리된 임시 DB에서 파일 해시와 DB 무결성을 확인합니다. 실제 데이터를 덮어쓰는 복원은 수행하지 않습니다. 백업 비밀번호는 저장소와
          분리해 보관하세요.
        </p>
        <p className='text-sm text-muted-foreground'>
          터미널에서 <code>uv run python scripts/local_backup.py --help</code>와 README의 백업 절차를 확인하세요.
        </p>
      </section>
    </div>
  );
}
