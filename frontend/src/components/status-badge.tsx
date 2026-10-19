import { Badge, type BadgeProps } from '@/components/ui/badge';

import { enumLabel } from '@/features/personal-data/consts/resources';

type Tone = NonNullable<BadgeProps['variant']>;

const TONE: Record<string, Tone> = {
  done: 'success',
  offer: 'success',
  confirmed: 'success',
  ready: 'success',
  active: 'accent',
  doing: 'accent',
  interviewing: 'accent',
  screening: 'accent',
  applied: 'accent',
  pending: 'warning',
  overdue: 'destructive',
  failed: 'destructive',
  rejected: 'default',
  withdrawn: 'default',
  dropped: 'default',
};

/** One look for domain status values everywhere; labels come from ENUM_LABEL. */
export function StatusBadge({ value, label, tone }: { value: string | null | undefined; label?: string; tone?: Tone }) {
  if (!value) return null;
  return <Badge variant={tone ?? TONE[value] ?? 'default'}>{label ?? enumLabel(value)}</Badge>;
}
