/** @see https://nextjs.org/docs/app/api-reference/config/next-config-js */
import type { NextConfig } from 'next';

// FastAPI backend. The browser only talks to this Next server; /api is proxied so cookies and CORS stay same-origin.
const serverDomain = process.env.SERVER_DOMAIN ?? 'http://127.0.0.1:8000';
// WSL on a Windows drive (/mnt/c/...) delivers no file-change events; poll instead.
const usePolling = process.cwd().startsWith('/mnt/');

const nextConfig: NextConfig = {
  // gzip buffers text/event-stream, which would hold the advisor answer until it finishes.
  compress: false,
  watchOptions: usePolling ? { pollIntervalMs: 500 } : undefined,
  experimental: {
    // Advisor answers stream longer than the 30s default proxy timeout.
    proxyTimeout: 10 * 60 * 1000,
  },
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          {
            key: 'Content-Security-Policy',
            value: [
              "default-src 'self'",
              "script-src 'self' 'unsafe-inline'" + (process.env.NODE_ENV === 'development' ? " 'unsafe-eval'" : ''),
              "style-src 'self' 'unsafe-inline'",
              "img-src 'self' data: blob:",
              "connect-src 'self'" + (process.env.NODE_ENV === 'development' ? ' ws://127.0.0.1:* ws://localhost:*' : ''),
              "frame-src 'none'",
              "frame-ancestors 'none'",
              "object-src 'none'",
              "base-uri 'self'",
              "form-action 'self'",
            ].join('; '),
          },
          { key: 'Referrer-Policy', value: 'no-referrer' },
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' },
        ],
      },
    ];
  },
  async rewrites() {
    return [
      { source: '/api/:path*', destination: `${serverDomain}/api/:path*` },
      { source: '/auth/callback', destination: `${serverDomain}/auth/callback` },
      { source: '/openapi.json', destination: `${serverDomain}/openapi.json` },
    ];
  },
};

export default nextConfig;
