import { expect, test } from '@playwright/test';

import { api, signIn } from './helpers';

// Synthetic data only. The backend runs a fake model provider; nothing leaves the machine.
test.describe.configure({ mode: 'serial' });

const CSV = '거래일,가맹점,이용금액\n2026-08-03,E2E Mart,"12,300"\n2026-08-15,E2E Cafe,4500\n';

test('first run: set a password and skip the start guide', async ({ page }) => {
  await signIn(page);
  const guide = page.getByRole('dialog', { name: '5분 시작 가이드' });
  await expect(guide).toBeVisible();
  await guide.getByRole('button', { name: '나중에 할게요' }).click();
  await expect(guide).toBeHidden();
  await page.reload();
  await expect(page.getByRole('heading', { name: '오늘' })).toBeVisible();
  await expect(page.getByRole('dialog', { name: '5분 시작 가이드' })).toBeHidden();
});

test('an account appears on the home figures and updates through the check-in sheet', async ({ page }) => {
  await signIn(page);
  const today = new Date().toISOString().slice(0, 10);
  await api(page, 'POST', '/api/data/accounts', {
    name: 'E2E 생활비 통장', kind: 'checking', currency: 'KRW', balance: '1000000', balance_as_of: today, is_liquid: true,
  });
  await page.goto('/finance/accounts');
  await page.getByRole('button', { name: '잔고 한 번에 업데이트' }).click();
  await page.getByLabel('E2E 생활비 통장 새 잔액').fill('1500000');
  await page.keyboard.press('Enter');
  await page.goto('/');
  await expect(page.getByText('생활비로 쓸 수 있는 현금')).toBeVisible();
  await expect(page.getByText(/150만/).first()).toBeVisible();
});

test('closing an edited record asks first, and the destructive confirm starts on 취소', async ({ page }) => {
  await signIn(page);
  await page.goto('/finance/accounts');
  await page.getByRole('button', { name: 'E2E 생활비 통장' }).click();
  const name = page.locator('#f-name');
  await name.fill('E2E 저장 안 한 이름');
  await page.keyboard.press('Escape');
  const discard = page.getByRole('alertdialog', { name: '저장하지 않은 변경을 버릴까요?' });
  await expect(discard.getByRole('button', { name: '취소' })).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(discard).toBeHidden();
  await expect(name).toHaveValue('E2E 저장 안 한 이름');
});

test('a card CSV imports once; importing it again adds nothing', async ({ page }) => {
  await signIn(page);
  await page.goto('/finance/cashflow');
  await page.getByRole('button', { name: '더보기' }).click();
  await expect(page.getByRole('menuitem', { name: '거래 추가' })).toBeVisible();
  await expect(page.getByRole('menuitem', { name: '오늘 평가액 기록' })).toBeVisible();
  await page.keyboard.press('Escape');
  for (const attempt of [1, 2]) {
    await page.getByRole('button', { name: '은행·카드 내역 가져오기' }).click();
    const dialog = page.getByRole('dialog', { name: '은행·카드 내역 가져오기' });
    await dialog.getByLabel('CSV 파일').setInputFiles({ name: 'e2e-card.csv', mimeType: 'text/csv', buffer: Buffer.from(CSV) });
    await dialog.getByLabel('지출 표시').selectOption('positive_is_expense');
    await dialog.getByRole('button', { name: '미리보기', exact: true }).click();
    if (attempt === 1) {
      await expect(dialog.getByText('가져올 새 기록')).toContainText('2건');
      await dialog.getByRole('button', { name: /2건 가져오기/ }).click();
      await expect(dialog).toBeHidden();
    } else {
      await expect(dialog.getByText('가져올 새 기록')).toContainText('0건');
      await expect(dialog.getByRole('button', { name: /0건 가져오기/ })).toBeDisabled();
      await page.keyboard.press('Escape');
    }
  }
});

test('a consultation proposal is approved from the review inbox and becomes a task', async ({ page }) => {
  await signIn(page);
  await page.goto('/advisor');
  await expect(page.getByRole('link', { name: '전송 확인하기' })).toBeVisible();
  await page.getByLabel('질문 입력').fill('전송 확인 전 질문');
  await expect(page.getByRole('button', { name: '보내기' })).toBeDisabled();
  await api(page, 'PUT', '/api/settings/transfer-policy', { training_excluded: true, retention_understood: true });
  await page.goto('/advisor');
  await page.getByLabel('질문 입력').fill('이번 주에 무엇부터 하면 좋을까?');
  await page.getByRole('button', { name: '보내기' }).click();
  await expect(page.getByText('합성 답변입니다.')).toBeVisible({ timeout: 45_000 });

  await page.goto('/review?view=approvals');
  await expect(page.getByText('E2E 합성 할 일').first()).toBeVisible();
  await page.getByRole('button', { name: '승인하고 반영' }).first().click();
  await expect(page.getByText('승인을 기다리는 항목이 없습니다')).toBeVisible();
  await page.goto('/plan/tasks');
  await expect(page.getByText('E2E 합성 할 일').first()).toBeVisible();
});

test('a conversation list that fails to load says so and loads on retry', async ({ page }) => {
  await signIn(page);
  const isList = (url: URL) => url.pathname === '/api/advisor/conversations';
  await page.route(isList, route => route.abort());
  await page.goto('/advisor');
  const failure = page.getByText(/상담 목록 불러오기 실패/);
  await expect(failure).toBeVisible();
  await page.unroute(isList);
  await page.getByRole('button', { name: '다시 시도' }).click();
  await expect(failure).toBeHidden();
  await expect(page.getByRole('link', { name: /이번 주에 무엇부터/ })).toBeVisible();
});

test('excluding finance from sharing removes it from what the model would receive', async ({ page }) => {
  await signIn(page);
  await api(page, 'PUT', '/api/settings/privacy', { excluded_categories: ['financial'] });
  const preview = await api<{ categories?: string[]; package?: { categories?: string[]; data?: Record<string, unknown> } }>(
    page,
    'POST',
    '/api/advisor/context/preview',
    { message: '생활비 통장 잔액 알려줘' },
  );
  const text = JSON.stringify(preview);
  expect(text).not.toContain('E2E 생활비 통장');
  expect(text).not.toContain('1500000');
  await api(page, 'PUT', '/api/settings/privacy', { excluded_categories: [] });
});

test('전체 잠금 in the menu locks the app', async ({ page }) => {
  await signIn(page);
  await page.getByRole('button', { name: '전체 잠금' }).click();
  await expect(page.getByRole('button', { name: '잠금 해제' })).toBeVisible();
});
