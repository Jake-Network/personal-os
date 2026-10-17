import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const api = process.env.PERSONAL_OS_API ?? 'http://127.0.0.1:8000';
// WSL on a Windows drive (/mnt/c/...) delivers no file-change events; poll instead.
const usePolling = process.cwd().startsWith('/mnt/');

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    watch: usePolling ? { usePolling: true, interval: 300 } : undefined,
    proxy: { '/api': api, '/openapi.json': api },
  },
  preview: { port: 5173, proxy: { '/api': api, '/openapi.json': api } },
});
