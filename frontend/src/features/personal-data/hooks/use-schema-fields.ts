import { useQuery } from '@tanstack/react-query';

import { customInstance } from '@/api-client/custom-client';

import { type OpenApiSpec, schemaFields } from '../utils/schema-fields';

export function useSchemaFields(resource: string) {
  return useQuery({
    queryKey: ['/openapi.json'],
    queryFn: () => customInstance<OpenApiSpec>({ url: '/openapi.json', method: 'GET' }),
    staleTime: Infinity,
    select: spec => schemaFields(spec, resource),
  });
}
