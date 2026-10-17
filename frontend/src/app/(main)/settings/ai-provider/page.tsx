import type { Metadata } from 'next';

import { AIProviderSettings } from '@/features/settings/components/ai-provider-settings';

export const metadata: Metadata = { title: 'AI Provider' };

const first = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v);

// The OAuth callback redirects here with result flags; reading them on the server keeps the client tree
// out of a Suspense boundary (useSearchParams), which would hydrate after the sidebar's queries resolve.
export default async function AIProviderPage({ searchParams }: PageProps<'/settings/ai-provider'>) {
  const params = await searchParams;
  return <AIProviderSettings callback={{ chatgpt: first(params.chatgpt), plan_usage: first(params.plan_usage), code: first(params.code) }} />;
}
