import { isAxiosError } from 'axios';

/** Backend errors normalized to one shape: `{ message, code }` from AdvisorError, or FastAPI's `detail`. */
export class ApiError extends Error {
  status: number;
  code?: string;

  constructor(status: number, message: string, code?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

interface ValidationIssue {
  loc?: (string | number)[];
  msg: string;
}

export function errorFromBody(status: number, body: unknown): ApiError {
  const b = (body ?? {}) as { message?: string; code?: string; detail?: unknown };
  if (b.message) return new ApiError(status, b.message, b.code);
  if (typeof b.detail === 'string') return new ApiError(status, b.detail);
  if (Array.isArray(b.detail)) {
    const msg = (b.detail as ValidationIssue[]).map(d => `${(d.loc ?? []).slice(1).join('.')}: ${d.msg}`).join('\n');
    return new ApiError(status, msg || '입력값을 확인하세요.');
  }
  return new ApiError(status, `요청 실패 (${status})`);
}

export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;
  if (isAxiosError(error)) {
    if (!error.response) return new ApiError(0, '서버에 연결할 수 없습니다.');
    return errorFromBody(error.response.status, error.response.data);
  }
  return new ApiError(0, error instanceof Error ? error.message : String(error));
}

export const errorMessage = (error: unknown) => toApiError(error).message;
