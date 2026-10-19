'use client';

import type { ReactNode } from 'react';

import { useGetLocale } from '@/api-client/generated/locale/locale';
import { setDisplayTimeZone } from '@/lib/utils/format';

/** Dates render and parse in PERSONAL_OS_TIMEZONE, so the app waits for it instead of guessing the browser zone. */
export function TimezoneGate({ children }: { children: ReactNode }) {
  const locale = useGetLocale({ query: { staleTime: Infinity, retry: 2 } });
  if (locale.isPending) return null;
  // Without an answer the browser zone is the only option; dates then may be a day off near midnight.
  setDisplayTimeZone(locale.data?.timezone);
  return children;
}
