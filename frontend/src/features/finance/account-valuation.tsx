import { QualityBadge } from '@/components/quality-badge';

import type { FinanceLine } from './api';
import { issueFlags, issueText } from './presentation';

export function AccountValuationStatus({ line, pending, failed }: { line?: FinanceLine; pending: boolean; failed: boolean }) {
  if (pending || failed || !line) {
    return <span className='text-xs text-muted-foreground'>{pending ? '확인 중' : failed ? '확인 실패' : '확인 필요'}</span>;
  }
  if (!line.issues.length) return <span className='text-xs text-faint'>확인됨</span>;
  return (
    <div className='flex flex-col items-start gap-1'>
      <QualityBadge flags={issueFlags(line.issues)} label={issueText(line.issues[0])} />
      {line.issues.includes('Stale balance/quantity') && (
        <span className='text-xs text-muted-foreground'>금액이 같다면 ‘잔고 그대로 맞음’을 눌러주세요.</span>
      )}
    </div>
  );
}

export function Spendability({ spendable }: { spendable?: boolean }) {
  return <span className='text-xs'>{spendable === undefined ? '확인 필요' : spendable ? '사용 가능' : '제외'}</span>;
}
