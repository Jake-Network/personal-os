import { defineConfig, devices } from '@playwright/test';

// Browser smoke tests against the real backend with a fake model provider (scripts/e2e_server.py).
// E2E_DATABASE_URL must name a disposable database ending in `_e2e`; it is wiped at start.
const API_PORT = process.env.E2E_API_PORT ?? '18000';
const WEB_PORT = process.env.E2E_WEB_PORT ?? '5174';
const baseURL = `http://127.0.0.1:${WEB_PORT}`;
const databaseUrl = process.env.E2E_DATABASE_URL ?? 'postgresql+psycopg://personal_os:personal_os@127.0.0.1:55432/personal_os_e2e';

export default defineConfig({
  testDir: './e2e',
  // One owner, one database: tests share state and run in order.
  workers: 1,
  fullyParallel: false,
  retries: process.env.CI ? 1 : 0,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: process.env.CI ? [['github'], ['list']] : 'list',
  use: { baseURL, trace: 'retain-on-failure', locale: 'ko-KR', ...devices['Desktop Chrome'] },
  webServer: [
    {
      command: 'uv run python scripts/e2e_server.py --reset',
      cwd: '..',
      url: `http://127.0.0.1:${API_PORT}/api/health`,
      timeout: 120_000,
      reuseExistingServer: false,
      env: {
        DATABASE_URL: databaseUrl,
        FRONTEND_URL: baseURL,
        OAUTH_CALLBACK_PORT: API_PORT,
        PERSONAL_OS_DATA_DIR: process.env.E2E_DATA_DIR ?? '/tmp/personal-os-e2e-data',
        PERSONAL_OS_TIMEZONE: 'Asia/Seoul',
      },
    },
    {
      command: process.env.E2E_SKIP_BUILD ? `corepack yarn next start -H 127.0.0.1 -p ${WEB_PORT}` : `corepack yarn build && corepack yarn next start -H 127.0.0.1 -p ${WEB_PORT}`,
      url: baseURL,
      timeout: 400_000,
      reuseExistingServer: false,
      env: { SERVER_DOMAIN: `http://127.0.0.1:${API_PORT}` },
    },
  ],
});
