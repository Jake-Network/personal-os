import axios, { type AxiosRequestConfig } from 'axios';

import { ApiError, toApiError } from './api-error';

// Same-origin: next.config.ts rewrites /api/* to the FastAPI server.
const instance = axios.create({ timeout: 60_000 });

instance.interceptors.response.use(
  response => response,
  error => Promise.reject(toApiError(error)),
);

/** orval mutator: every generated hook goes through here. */
export const customInstance = async <T>(config: AxiosRequestConfig, options?: AxiosRequestConfig): Promise<T> => {
  const { data } = await instance.request<T>({ ...config, ...options });
  return data;
};

// orval passes the spec's error schema; every error is normalized to ApiError by the interceptor above.
// eslint-disable-next-line @typescript-eslint/no-unused-vars
export type ErrorType<_Error> = ApiError;
export type BodyType<BodyData> = BodyData;
