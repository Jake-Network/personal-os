import type { GoogleOAuthSetup } from './api';

export function googleOriginMismatch(browserOrigin: string, setup?: GoogleOAuthSetup): boolean {
  if (!browserOrigin || !setup) return false;
  try {
    return new URL(setup.frontend_url).origin !== browserOrigin;
  } catch {
    return true;
  }
}

export function googleEnvironmentTemplate(setup: GoogleOAuthSetup): string {
  return [
    'GOOGLE_OAUTH_CLIENT_ID=',
    'GOOGLE_OAUTH_CLIENT_SECRET=',
    `GOOGLE_OAUTH_REDIRECT_URI=${JSON.stringify(setup.redirect_uri)}`,
    `FRONTEND_URL=${JSON.stringify(setup.frontend_url)}`,
  ].join('\n');
}
