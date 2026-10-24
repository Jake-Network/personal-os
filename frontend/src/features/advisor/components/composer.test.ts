import { createElement, type ReactNode } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { expect, it, vi } from 'vitest';

import type { AdvisorSend } from '../hooks/use-advisor-send';
import { AutomaticRecordingToggle, ShareSummary } from './composer';
import { initialDraft } from '../utils/send-logic';

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

it('shows automatic recording as an explicit disabled-by-default control with its scope', () => {
  const send = { draft: initialDraft(1, null), updateDraft: () => {}, busy: false };
  const html = renderToStaticMarkup(createElement(AutomaticRecordingToggle, { send }));
  expect(html).toContain('자동 기록');
  expect(html).toContain('aria-checked="false"');
  expect(html).toContain('말한 실적·잔액·보유량을 기록합니다. 삭제는 직접 요청해야 합니다.');
  const enabled = renderToStaticMarkup(createElement(AutomaticRecordingToggle, { send: { ...send, draft: { ...send.draft, allowDataRecording: true }, busy: true } }));
  expect(enabled).toContain('aria-checked="true"');
  expect(enabled).toContain('disabled=""');
});
