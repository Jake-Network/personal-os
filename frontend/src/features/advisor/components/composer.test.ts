import { createElement, type ReactNode } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { expect, it, vi } from 'vitest';

import type { AdvisorSend } from '../hooks/use-advisor-send';
import { ShareSummary } from './composer';

vi.mock('@/components/ui/popover', () => ({
  Popover: ({ children }: { children: ReactNode }) => createElement('div', null, children),
  PopoverTrigger: ({ children }: { children: ReactNode }) => createElement('button', null, children),
  PopoverContent: ({ children }: { children: ReactNode }) => createElement('div', null, children),
}));

it('shows the personal profile when all other records are excluded', () => {
  const send = { input: '내 제약을 알려줘', preview: { categories: ['profile'] } } as unknown as AdvisorSend;
  const html = renderToStaticMarkup(createElement(ShareSummary, { send, privacyBlocked: [] }));
  expect(html).toContain('개인 프로필 공유');
  expect(html).not.toContain('개인 기록 공유 안 함');
});

it('only reports no personal records when the preview has no categories', () => {
  const send = { input: '일반적인 질문', preview: { categories: [] } } as unknown as AdvisorSend;
  const html = renderToStaticMarkup(createElement(ShareSummary, { send, privacyBlocked: ['profile'] }));
  expect(html).toContain('개인 기록 공유 안 함');
});

it('keeps profile sharing read-only and points to the setting that can change it', () => {
  const send = { input: '내 제약을 알려줘', preview: { categories: ['profile'] }, busy: false } as unknown as AdvisorSend;
  const html = renderToStaticMarkup(createElement(ShareSummary, { send, privacyBlocked: [] }));
  const profileSwitch = html.match(/<button[^>]*id="share-profile"[^>]*>/)?.[0];
  expect(profileSwitch).toContain('disabled=""');
  expect(html).toContain('개인 프로필 공유는 기본 공유 설정에서 변경할 수 있습니다.');
  expect(html).toContain('href="/settings/privacy"');
});
