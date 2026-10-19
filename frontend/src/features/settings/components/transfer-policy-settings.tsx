'use client';

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { customInstance } from '@/api-client/custom-client';
import type { TransferPolicyStatus } from '@/api-client/model/transferPolicyStatus';
import { notify } from '@/components/notify';
import { Button } from '@/components/ui/button';
import { Section } from '@/components/page-container';
import { QueryStatus } from '@/components/query-status';
import { Badge } from '@/components/ui/badge';
import { Checkbox } from '@/components/ui/checkbox';

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
    <Section
      title='개인 데이터 전송 확인'
      actions={policy.data && (policy.data.confirmed ? <Badge variant='success'>확인 완료</Badge> : <Badge variant='warning'>확인 필요 · 상담 전송 막힘</Badge>)}>
      <div className='flex flex-col gap-3 py-2'>
        <QueryStatus pending={policy.isPending} error={policy.error} retry={policy.refetch} label='전송 확인 상태' rows={1} />
        <p className='text-muted-foreground'>
          상담에서 개인 데이터를 보내기 전에, 연결한 계정의 학습·보관 정책을 직접 확인해 주세요. 앱은 제공자 계정 설정을 볼 수 없습니다.{' '}
          <a href='https://developers.openai.com/api/docs/guides/your-data' target='_blank' rel='noreferrer' className='text-primary hover:underline'>
            OpenAI 데이터 정책
          </a>
        </p>
        <label className='flex items-start gap-2'>
          <Checkbox className='mt-0.5' checked={training} onCheckedChange={v => setTraining(v === true)} />
          연결한 계정에서 보낸 데이터가 모델 학습에 쓰이지 않도록 설정되어 있음을 확인했습니다.
        </label>
        <label className='flex items-start gap-2'>
          <Checkbox className='mt-0.5' checked={retention} onCheckedChange={v => setRetention(v === true)} />
          제공자의 외부 보관 정책을 확인했고, 학습 제외와 보관하지 않음은 다르다는 것을 이해합니다.
        </label>
        <div className='flex flex-wrap gap-2'>
          <Button variant='primary' disabled={!training || !retention || !policy.data?.account_available || save.isPending} onClick={() => save.mutate(false)}>
            확인 저장
          </Button>
          <Button disabled={!policy.data?.confirmed || save.isPending} onClick={() => save.mutate(true)}>
            확인 철회
          </Button>
        </div>
        <details className='text-ui'>
          <summary className='cursor-pointer text-muted-foreground'>고급</summary>
          <p className='mt-2 text-muted-foreground'>요청에는 응답 저장을 끄는 옵션(store: false)을 붙입니다. 제공자의 보안·보관 정책은 그와 별도로 적용됩니다.</p>
        </details>
      </div>
    </Section>
  );
}
