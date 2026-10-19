import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { displayTimeZone, setDisplayTimeZone } from '@/lib/utils/format';

import { TimezoneGate } from './timezone-gate';

const { locale } = vi.hoisted(() => ({ locale: vi.fn() }));
vi.mock('@/api-client/generated/locale/locale', () => ({ useGetLocale: locale }));

afterEach(() => setDisplayTimeZone(undefined));

describe('timezone gate', () => {
  const render = () => renderToStaticMarkup(createElement(TimezoneGate, null, createElement('form', null, '일정 입력')));

  it('keeps date inputs unavailable after a locale failure and offers retry', () => {
    locale.mockReturnValue({ isPending: false, error: new Error('연결 실패'), refetch: vi.fn() });
    const html = render();
    expect(html).not.toContain('일정 입력');
    expect(html).toContain('다시 시도');
    expect(html).toContain('시간대');
  });

  it('uses the server timezone before rendering date inputs', () => {
    locale.mockReturnValue({ isPending: false, data: { timezone: 'Asia/Seoul' }, refetch: vi.fn() });
    expect(render()).toContain('일정 입력');
    expect(displayTimeZone()).toBe('Asia/Seoul');
  });
});
