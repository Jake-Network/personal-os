'use client';

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { customInstance } from '@/api-client/custom-client';
import type { TransferPolicyStatus } from '@/api-client/model/transferPolicyStatus';
import { notify } from '@/components/notify';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

const key = ['/api/settings/transfer-policy'];

export function TransferPolicySettings({ provider }: { provider?: string }) {
  const client = useQueryClient();
  const [training, setTraining] = useState(false);
  const [retention, setRetention] = useState(false);
  const policy = useQuery({ queryKey: [...key, provider], queryFn: () => customInstance<TransferPolicyStatus>({ url: key[0] }) });
  const save = useMutation({
    mutationFn: (revoke: boolean) =>
      customInstance({
        url: key[0],
        method: revoke ? 'DELETE' : 'PUT',
        data: revoke ? undefined : { training_excluded: training, retention_understood: retention },
      }),
    onSuccess: () => {
      setTraining(false);
      setRetention(false);
      void client.invalidateQueries({ queryKey: key });
    },
    onError: notify.error,
  });
  return (
    <Card className='mb-3.5'>
      <CardHeader>
        <CardTitle>개인 데이터 외부 전송 확인</CardTitle>
      </CardHeader>
      <CardContent className='flex flex-col gap-3'>
        <p>현재 계정: {policy.data?.confirmed ? '사용자 확인 완료' : '정책 확인 필요 · 상담 전송 차단'}</p>
        <p className='text-sm text-faint'>
          앱은 제공자의 계정 설정을 직접 확인할 수 없습니다. store: false를 사용하며, 제공자의 보안·보관 정책은 별도로 적용됩니다.
        </p>
        <a href='https://developers.openai.com/api/docs/guides/your-data' target='_blank' rel='noreferrer' className='underline'>
          OpenAI 데이터 통제 정책
        </a>
        <label className='flex items-start gap-2'>
          <input type='checkbox' checked={training} onChange={e => setTraining(e.target.checked)} />
          현재 연결 계정의 학습 사용 정책과 설정을 확인했고, 전송 데이터가 학습에서 제외됨을 확인했습니다.
        </label>
        <label className='flex items-start gap-2'>
          <input type='checkbox' checked={retention} onChange={e => setRetention(e.target.checked)} />
          외부 보관 정책을 확인했습니다. 학습 제외와 외부 보관 없음은 서로 다름을 이해합니다.
        </label>
        {policy.error && <p role='alert'>{policy.error.message}</p>}
        <div className='flex gap-2'>
          <Button disabled={!training || !retention || !policy.data?.account_available || save.isPending} onClick={() => save.mutate(false)}>
            현재 계정 확인 저장
          </Button>
          <Button disabled={!policy.data?.confirmed || save.isPending} onClick={() => save.mutate(true)}>
            전송 확인 철회
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
