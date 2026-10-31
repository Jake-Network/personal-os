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
  await page.getByRole('button', { name: /1개 계좌 저장/ }).click();
  await page.goto('/');
  await expect(page.getByText('생활비로 쓸 수 있는 현금')).toBeVisible();
  await expect(page.getByText(/150만/).first()).toBeVisible();
});

test('a card CSV imports once; importing it again adds nothing', async ({ page }) => {
  await signIn(page);
  await page.goto('/finance/cashflow');
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
