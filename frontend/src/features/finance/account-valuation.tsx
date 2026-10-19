import { QualityBadge } from '@/components/quality-badge';

import type { FinanceLine } from './api';
import { issueFlags } from './presentation';

export function AccountValuationStatus({ line, pending, failed }: { line?: FinanceLine; pending: boolean; failed: boolean }) {
  if (pending || failed || !line) {
    return <span className='text-xs text-muted-foreground'>{pending ? '확인 중' : failed ? '확인 실패' : '확인 필요'}</span>;
  }
  return line.issues.length ? <QualityBadge flags={issueFlags(line.issues)} /> : <span className='text-xs text-faint'>확인됨</span>;
}

export function Spendability({ spendable }: { spendable?: boolean }) {
  return <span className='text-xs'>{spendable === undefined ? '확인 필요' : spendable ? '사용 가능' : '제외'}</span>;
}
