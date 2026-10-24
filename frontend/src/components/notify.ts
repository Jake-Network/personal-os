'use client';

import { toast } from 'sonner';

import { errorMessage } from '@/api-client/api-error';

export const notify = {
  success: (title: string) => toast.success(title),
  info: (title: string) => toast(title),
  error: (error: unknown) => toast.error(typeof error === 'string' ? error : errorMessage(error)),
};
