import type { Metadata } from 'next';

import { DocumentsView } from '@/features/documents/documents-view';

export const metadata: Metadata = { title: '문서함' };

export default function DocumentsPage() {
  return <DocumentsView />;
}
