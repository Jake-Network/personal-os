import { customInstance } from '@/api-client/custom-client';
import type { CareerRecordItem, TimelinePage } from '@/api-client/model';

export type CareerRecord = Required<CareerRecordItem>;

export const careerApi = {
  list: () => customInstance<CareerRecord[]>({ url: '/api/career/records' }),
  save: (data: Record<string, unknown>, id?: number) =>
    customInstance<CareerRecord>({
      url: id ? `/api/career/records/${id}` : '/api/career/records',
      method: id ? 'PUT' : 'POST',
      data,
    }),
  confirm: (id: number) => customInstance<CareerRecord>({ url: `/api/career/records/${id}/confirm`, method: 'POST' }),
  remove: (id: number) => customInstance<void>({ url: `/api/career/records/${id}`, method: 'DELETE' }),
  timeline: (params: Record<string, string | number | undefined>) =>
    customInstance<TimelinePage>({ url: '/api/timeline', params }),
};
