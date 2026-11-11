import { expect, test } from '@playwright/test';

import { signIn } from './helpers';

// Phone-width pass over every screen, after the desktop specs have left synthetic data behind.
const ROUTES = [
  '/',
  '/advisor',
  '/plan',
  '/plan/tasks',
  '/plan/events',
  '/plan/goals',
  '/plan/workouts',
  '/finance',
  '/finance/accounts',
  '/finance/investments',
  '/finance/cashflow',
  '/finance/history',
  '/career',
  '/career/records',
  '/career/timeline',
  '/career/criteria',
  '/reflect',
  '/reflect/reviews',
  '/reflect/playbooks',
  '/documents',
  '/review',
  '/settings/ai-provider',
  '/settings/memory',
  '/settings/agent',
  '/settings/privacy',
  '/settings/market',
  '/settings/jobs',
  '/settings/security',
  '/settings/display',
];

test('every screen renders at phone width without sideways scrolling', async ({ page }) => {
  test.setTimeout(120_000);
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(`${page.url()}: ${error.message}`));
  await signIn(page);
  const overflowing: string[] = [];
  for (const route of ROUTES) {
    await page.goto(route);
    await expect(page.locator('main').locator('h1, h2').first(), route).toBeVisible();
    await expect(page.locator('main').getByText('불러오는 중'), `${route} still loading`).toHaveCount(0);
    const fits = await page.evaluate(() => {
      const main = document.querySelector('main');
      return document.documentElement.scrollWidth <= window.innerWidth && (!main || main.scrollWidth <= main.clientWidth);
    });
    if (!fits) overflowing.push(route);
  }
  expect(errors).toEqual([]);
  expect(overflowing).toEqual([]);
});

test('a sheet that fills the screen closes from its close button', async ({ page }) => {
  await signIn(page);
  await page.goto('/finance/accounts');
  await page.getByRole('button', { name: 'E2E 생활비 통장' }).click();
  const sheet = page.getByRole('dialog', { name: '계좌 수정' });
  await sheet.getByRole('button', { name: '닫기' }).click();
  await expect(sheet).toBeHidden();
});

test('the 더보기 menu reaches the areas that are not in the tab bar', async ({ page }) => {
  await signIn(page);
  await page.getByRole('button', { name: '더보기' }).click();
  const menu = page.getByRole('dialog', { name: '메뉴' });
  await expect(menu.getByRole('button', { name: '전체 잠금' })).toBeVisible();
  await menu.getByRole('link', { name: '커리어' }).click();
  await expect(page).toHaveURL(/\/career$/);
  await expect(page.getByRole('dialog', { name: '메뉴' })).toBeHidden();
});
