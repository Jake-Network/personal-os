'use client';

import { useQueryClient } from '@tanstack/react-query';

import { notify } from '@/components/notify';
import { PageContainer, PageHeader } from '@/components/page-container';
import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Card } from '@/components/ui/card';
import { Switch } from '@/components/ui/switch';

import { getGetPrivacyQueryKey, useGetPrivacy, usePutPrivacy } from '@/api-client/generated/privacy/privacy';
import type { Category, PrivacySettings } from '@/api-client/model';
import { ALL_CATEGORIES, CATEGORY_HINT, CATEGORY_LABEL } from '@/lib/labels';

export function PrivacySettingsView() {
  const queryClient = useQueryClient();
  const privacy = useGetPrivacy();
  const queryKey = getGetPrivacyQueryKey();

  // Optimistic: the switch flips immediately and rolls back if the save fails.
  const save = usePutPrivacy({
    mutation: {
      onMutate: async ({ data }) => {
        await queryClient.cancelQueries({ queryKey });
        const previous = queryClient.getQueryData<PrivacySettings>(queryKey);
        queryClient.setQueryData(queryKey, data);
        return { previous };
      },
      onError: (e, _vars, context) => {
        queryClient.setQueryData(queryKey, context?.previous);
        notify.error(e);
      },
      onSuccess: data => queryClient.setQueryData(queryKey, data),
    },
  });

  const excluded = privacy.data ? new Set<Category>(privacy.data.excluded_categories) : null;

  function toggle(c: Category) {
    if (!excluded) return;
    const next = new Set(excluded);
    if (next.has(c)) next.delete(c);
    else next.add(c);
    save.mutate({ data: { excluded_categories: [...next] } });
  }

  return (
    <PageContainer className='max-w-[720px]'>
      <PageHeader
        title='데이터 공유'
        description='꺼 둔 영역의 데이터는 어떤 질문에서도 외부 모델로 전송되지 않습니다. 질문할 때 영역별로 한 번 더 조정할 수 있습니다.'
        actions={save.isSuccess && <Badge variant='success'>저장됨</Badge>}
      />
      {privacy.error && (
        <Alert variant='destructive' className='mb-3'>
          {privacy.error.message}
        </Alert>
      )}
      <Card>
        <ul>
          {ALL_CATEGORIES.map(c => (
            <li key={c} className='flex items-center gap-2.5 border-b px-4 py-2.5 last:border-0'>
              <div className='flex-1'>
                <strong>{CATEGORY_LABEL[c]}</strong>
                <div className='text-xs text-faint'>{CATEGORY_HINT[c]}</div>
              </div>
              {excluded && (excluded.has(c) ? <Badge variant='destructive'>전송 안 함</Badge> : <Badge variant='success'>AI와 공유</Badge>)}
              <Switch
                disabled={!excluded}
                checked={excluded ? !excluded.has(c) : false}
                onCheckedChange={() => toggle(c)}
                aria-label={`${CATEGORY_LABEL[c]} 공유`}
              />
            </li>
          ))}
        </ul>
      </Card>
      <p className='mt-3 text-xs text-faint'>
        계좌번호와 인증정보는 설정과 상관없이 저장·전송하지 않습니다. 대시보드처럼 이 기기 안에서만 보는 화면에는 이 설정이 적용되지 않습니다.
      </p>
    </PageContainer>
  );
}
