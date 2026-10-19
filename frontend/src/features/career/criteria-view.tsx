'use client';

import { ResourceTable } from '@/features/personal-data/components/data-table-view';

/** What matters when comparing offers; the advisor weighs options against these. */
export function CriteriaView({ recordId }: { recordId: number | null }) {
  return (
    <ResourceTable
      resource='career-criteria'
      title='평가 기준'
      recordId={recordId}
      addLabel='기준 추가'
      emptyText='연봉, 성장, 출퇴근처럼 회사를 비교할 기준과 가중치(1–10)를 정해 두세요.'
    />
  );
}
