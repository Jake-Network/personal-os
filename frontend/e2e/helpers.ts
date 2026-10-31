import { expect, type Page } from '@playwright/test';

export const PASSWORD = 'e2e-synthetic-password';

/** First run sets the owner password; later runs in the same database unlock with it. */
export async function signIn(page: Page) {
  await page.goto('/');
  const field = page.getByLabel(/비밀번호/);
  await expect(field).toBeVisible();
  await field.fill(PASSWORD);
  await page.getByRole('button', { name: /비밀번호 설정|잠금 해제/ }).click();
  await expect(page.getByRole('navigation', { name: '주 메뉴' })).toBeVisible();
}

/** A JSON API call as the signed-in owner (session cookie + CSRF header), for seeding synthetic data. */
export async function api<T = unknown>(page: Page, method: 'GET' | 'POST' | 'PUT' | 'DELETE', url: string, data?: unknown): Promise<T> {
  const status = await (await page.request.get('/api/security/status')).json();
  const response = await page.request.fetch(url, {
    method,
    data,
    headers: { 'X-CSRF-Token': status.csrf_token ?? '', Origin: new URL(page.url()).origin },
  });
  expect(response.ok(), `${method} ${url}: ${response.status()} ${await response.text()}`).toBeTruthy();
  return (response.status() === 204 ? undefined : await response.json()) as T;
}
