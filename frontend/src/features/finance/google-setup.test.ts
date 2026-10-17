import { describe, expect, it } from 'vitest';

import type { GoogleOAuthSetup } from './api';
import { googleEnvironmentTemplate, googleOriginMismatch } from './google-setup';

const setup: GoogleOAuthSetup = {
  missing_fields: ['GOOGLE_OAUTH_CLIENT_ID', 'GOOGLE_OAUTH_CLIENT_SECRET'],
  frontend_url: 'http://127.0.0.1:5173',
  redirect_uri: 'http://127.0.0.1:8000/api/finance/google/callback',
  login_url: 'http://127.0.0.1:5173/finance',
  redirect_uri_supported: true,
  callback_host_matches_frontend: true,
};

describe('Google setup guidance', () => {
  it('warns for a private-IP browser origin without warning during server rendering or older status responses', () => {
    expect(googleOriginMismatch('http://172.18.224.169:5173', setup)).toBe(true);
    expect(googleOriginMismatch('http://127.0.0.1:5173', setup)).toBe(false);
    expect(googleOriginMismatch('', setup)).toBe(false);
    expect(googleOriginMismatch('http://127.0.0.1:5173')).toBe(false);
  });

  it('compares complete origins, including ports and protocols', () => {
    expect(googleOriginMismatch('http://127.0.0.1:3000', setup)).toBe(true);
    expect(googleOriginMismatch('https://127.0.0.1:5173', setup)).toBe(true);
    expect(googleOriginMismatch('http://localhost:5173', setup)).toBe(true);
  });

  it('provides empty credential placeholders and exact server-configured URLs', () => {
    expect(googleEnvironmentTemplate(setup)).toBe(
      'GOOGLE_OAUTH_CLIENT_ID=\nGOOGLE_OAUTH_CLIENT_SECRET=\n' +
        'GOOGLE_OAUTH_REDIRECT_URI="http://127.0.0.1:8000/api/finance/google/callback"\n' +
        'FRONTEND_URL="http://127.0.0.1:5173"',
    );
  });
});
