import { defineConfig } from 'orval';

// The backend must be running (or point OPENAPI_TARGET at a saved openapi.json).
const target = process.env.OPENAPI_TARGET ?? `${process.env.SERVER_DOMAIN ?? 'http://127.0.0.1:8000'}/openapi.json`;

export default defineConfig({
  main: {
    input: { target },
    output: {
      mode: 'tags-split',
      target: 'src/api-client/generated',
      schemas: 'src/api-client/model',
      client: 'react-query',
      httpClient: 'axios',
      clean: true,
      override: {
        mutator: {
          path: 'src/api-client/custom-client.ts',
          name: 'customInstance',
        },
        // Orval selects query/mutation hooks by HTTP method. Retry/refetch
        // defaults live on the QueryClient (src/lib/react-query-hooks).
      },
    },
  },
});
