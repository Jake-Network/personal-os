import type { Metadata } from 'next';

import { AdvisorWorkspace } from '@/features/advisor/components/advisor-workspace';

export const metadata: Metadata = { title: 'AI 상담' };

// The workspace lives in the layout so it is not remounted when /advisor becomes /advisor/[id]
// (a page would be, and a just-started answer stream would be lost). The pages below render nothing.
export default function AdvisorLayout({ children }: { children: React.ReactNode }) {
  return (
    <>
      <AdvisorWorkspace />
      {children}
    </>
  );
}
