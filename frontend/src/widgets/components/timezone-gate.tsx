'use client';

import type { ReactNode } from 'react';

import { useGetLocale } from '@/api-client/generated/locale/locale';
import { QueryStatus } from '@/components/query-status';
import { setDisplayTimeZone } from '@/lib/utils/format';

/** Dates render and parse in PERSONAL_OS_TIMEZONE, so the app waits for it instead of guessing the browser zone. */
export function TimezoneGate({ children }: { children: ReactNode }) {
  const locale = useGetLocale({ query: { staleTime: Infinity, retry: 2 } });
  if (locale.isPending || locale.error || !locale.data?.timezone)
    return (
      <div className='p-4'>
        <QueryStatus
          pending={locale.isPending}
          error={locale.error ?? (!locale.isPending ? new Error('시간대 정보를 확인하지 못했습니다') : null)}
          retry={locale.refetch}
          label='시간대'
        />
      </div>
    );
  setDisplayTimeZone(locale.data.timezone);
  return children;
}
