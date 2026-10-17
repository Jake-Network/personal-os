import { Card } from '@/components/ui/card';

export function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <Card className='p-4'>
      <div className='text-xs text-muted-foreground'>{label}</div>
      <div className='mt-0.5 text-[22px] font-bold tabular-nums tracking-tight'>{value}</div>
      {sub && <div className='mt-0.5 text-xs text-faint'>{sub}</div>}
    </Card>
  );
}
