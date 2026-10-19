'use client';

import { useQueryClient } from '@tanstack/react-query';

import { notify } from '@/components/notify';
import { Section } from '@/components/page-container';
import { Alert } from '@/components/ui/alert';
import { Switch } from '@/components/ui/switch';

import { getGetPrivacyQueryKey, useGetPrivacy, usePutPrivacy } from '@/api-client/generated/privacy/privacy';
import type { Category, PrivacySettings } from '@/api-client/model';
import { RecordSharing } from './record-sharing';
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
    <div className='max-w-[720px]'>
      <Section title='AI와 공유할 영역' info={<p>질문할 때마다 영역별로 한 번 더 조정할 수 있습니다. 홈처럼 이 기기 안에서만 보는 화면에는 적용되지 않습니다.</p>}>
        <p className='py-1 text-ui text-muted-foreground'>꺼 둔 영역은 어떤 질문에서도 외부 AI로 보내지 않습니다.</p>
        {privacy.error && <Alert variant='destructive'>{privacy.error.message}</Alert>}
        <ul className='divide-y'>
          {ALL_CATEGORIES.map(c => {
            const shared = excluded ? !excluded.has(c) : false;
            return (
              <li key={c} className='flex items-center gap-3 py-2.5'>
                <div className='flex-1'>
                  <span className='font-medium'>{CATEGORY_LABEL[c]}</span>
                  <span className='block text-xs text-muted-foreground'>{CATEGORY_HINT[c]}</span>
                </div>
                <span className='w-14 text-right text-xs text-muted-foreground' aria-hidden>
                  {excluded ? (shared ? '공유' : '보내지 않음') : ''}
                </span>
                <Switch disabled={!excluded} checked={shared} onCheckedChange={() => toggle(c)} aria-label={`${CATEGORY_LABEL[c]} AI와 공유`} />
              </li>
            );
          })}
        </ul>
        <p className='mt-2 text-xs text-faint'>계좌번호와 인증정보는 이 설정과 관계없이 저장하거나 보내지 않습니다.</p>
      </Section>
      <RecordSharing />
    </div>
  );
}
