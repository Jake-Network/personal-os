import { AreaLayout } from '@/components/area-layout';

const TABS = [
  { href: '/finance', label: '개요', end: true },
  { href: '/finance/accounts', label: '계좌·부채' },
  { href: '/finance/investments', label: '투자' },
  { href: '/finance/transactions', label: '거래' },
  { href: '/finance/history', label: '월별 기록' },
];

export default function FinanceLayout({ children }: { children: React.ReactNode }) {
  return (
    <AreaLayout title='자산' tabs={TABS}>
      {children}
    </AreaLayout>
  );
}
