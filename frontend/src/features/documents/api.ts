import { customInstance } from '@/api-client/custom-client';

export interface PersonalDocument {
  id: number;
  title: string;
  categories: string[];
  kind: string;
  as_of: string | null;
  sharing_enabled: boolean;
  status: string;
  error: string | null;
  active_version_id: number | null;
  latest_version_id: number | null;
  filename: string;
  created_at: string;
  updated_at: string;
}

export interface DocumentCitation {
  historical?: boolean;
  ref: string;
  document_id: number;
  version_id: number;
  title: string;
  filename: string;
  page: number | null;
  section: string | null;
  text: string;
  as_of: string | null;
}

export interface DocumentVersion {
  id: number;
  filename: string;
  as_of: string | null;
  status: string;
  error: string | null;
  created_at: string;
}

export const documentsKey = ['personal-documents'] as const;
export const documentsApi = {
  list: () => customInstance<PersonalDocument[]>({ url: '/api/documents' }),
  upload: (data: FormData) => customInstance<PersonalDocument>({ url: '/api/documents', method: 'POST', data }),
  replace: (id: number, data: FormData) => customInstance<PersonalDocument>({ url: `/api/documents/${id}/versions`, method: 'POST', data }),
  versions: (id: number) => customInstance<DocumentVersion[]>({ url: `/api/documents/${id}/versions` }),
  reindex: (id: number) => customInstance<PersonalDocument>({ url: `/api/documents/${id}/reindex`, method: 'POST' }),
  retry: (id: number) => customInstance<PersonalDocument>({ url: `/api/documents/${id}/retry`, method: 'POST' }),
  update: (id: number, data: Partial<Pick<PersonalDocument, 'title' | 'categories' | 'kind' | 'sharing_enabled'>>) =>
    customInstance<PersonalDocument>({ url: `/api/documents/${id}`, method: 'PATCH', data }),
  remove: (id: number, purgeEvidence: boolean) =>
    customInstance<void>({ url: `/api/documents/${id}`, method: 'DELETE', params: { purge_evidence: purgeEvidence } }),
};
