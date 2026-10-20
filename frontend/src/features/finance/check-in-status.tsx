import type { Snapshot } from './api';
import { monthLabel } from '@/lib/utils/format';

export function CheckInStatus({
  todayConfirmed,
  month,
  snapshot,
  pending,
  failed,
}: {
  todayConfirmed: boolean;
  month: string;
  snapshot?: Pick<Snapshot, 'complete'>;
  pending: boolean;
  failed: boolean;
}) {
  const status = snapshot
    ? snapshot.complete
      ? '월말 기록 완료'
      : '월말 기록 근거 부족'
    : failed
      ? '월말 기록 확인 실패'
      : pending
        ? '월말 기록 확인 중'
        : '월말 기록 미완료';
  return (
    <p className='text-ui' role='status'>
      {todayConfirmed ? '오늘 확인 완료' : '오늘 확인 미완료'} / {monthLabel(month)} {status}
    </p>
  );
}
