import { expect, test, type Locator, type Page } from '@playwright/test';

import { signIn } from './helpers';

const CSV = '거래일,금액,대체금액,적요\n2026-08-03,12300,4500,Synthetic Mart\n';

async function openImport(page: Page) {
  await signIn(page);
  await page.goto('/finance/cashflow');
  await page.getByRole('button', { name: '은행·카드 내역 가져오기' }).click();
  const dialog = page.getByRole('dialog', { name: '은행·카드 내역 가져오기' });
  await dialog.getByLabel('CSV 파일').setInputFiles({ name: 'preview-regression.csv', mimeType: 'text/csv', buffer: Buffer.from(CSV) });
  return dialog;
}

const changes: [string, (dialog: Locator) => Promise<unknown>][] = [
  ['amount sign', dialog => dialog.getByLabel('지출 표시').selectOption('positive_is_expense')],
  ['column mapping', dialog => dialog.getByLabel('금액', { exact: true }).selectOption('대체금액')],
  ['source identity', dialog => dialog.getByLabel('원본 이름 (같은 계좌·카드는 같게)').fill('changed-source')],
  ['header offset', dialog => dialog.getByLabel('머리글 앞 줄 수').fill('1')],
  ['amount shape', dialog => dialog.getByLabel('금액 열', { exact: true }).selectOption('split')],
];

for (const [name, change] of changes) {
  test(`cashflow preview must be reviewed again after changing ${name}`, async ({ page }) => {
    const dialog = await openImport(page);
    await dialog.getByRole('button', { name: '미리보기', exact: true }).click();
    await expect(dialog.getByRole('button', { name: '1건 가져오기', exact: true })).toBeVisible();
    await change(dialog);
    await expect(dialog.getByRole('button', { name: '1건 가져오기', exact: true })).toBeHidden();
    await expect(dialog.getByRole('cell', { name: 'Synthetic Mart', exact: true })).toBeHidden();
  });
}

test('a late cashflow preview response cannot authorize changed inputs', async ({ page }) => {
  const dialog = await openImport(page);
  let release!: () => void;
  const blocked = new Promise<void>(resolve => {
    release = resolve;
  });
  let received!: () => void;
  const requestReceived = new Promise<void>(resolve => {
    received = resolve;
  });
  await page.route('**/api/finance/cashflow/import/preview', async route => {
    const response = await route.fetch();
    received();
    await blocked;
    await route.fulfill({ response });
  });
  await dialog.getByRole('button', { name: '미리보기', exact: true }).click();
  await requestReceived;
  await dialog.getByLabel('지출 표시').selectOption('positive_is_expense');
  const completed = page.waitForResponse('**/api/finance/cashflow/import/preview');
  release();
  await completed;
  await expect(dialog.getByRole('button', { name: '미리보기', exact: true })).toBeEnabled();
  await expect(dialog.getByRole('button', { name: '1건 가져오기', exact: true })).toBeHidden();
  await page.unroute('**/api/finance/cashflow/import/preview');
  await dialog.getByRole('button', { name: '미리보기', exact: true }).click();
  await expect(dialog.getByRole('button', { name: '1건 가져오기', exact: true })).toBeVisible();
});
