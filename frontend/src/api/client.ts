import type { AnalysisRequest, AnalysisResponse, DiagnosisRequest, DiagnosisResponse, ErrorResponse } from './types';

export const ANALYSIS_TIMEOUT_MS = 100_000;
export const DIAGNOSIS_TIMEOUT_MS = 60_000;

export class ApiError extends Error {
  constructor(message: string, public code: string, public retryable: boolean,
    public requestId?: string, public details: string[] = [], public status?: number) {
    super(message);
    this.name = 'ApiError';
  }
}

function isErrorResponse(value: unknown): value is ErrorResponse {
  if (!value || typeof value !== 'object' || !('error' in value)) return false;
  const error = value.error;
  return !!error && typeof error === 'object' &&
    'code' in error && typeof error.code === 'string' &&
    'message' in error && typeof error.message === 'string' &&
    'retryable' in error && typeof error.retryable === 'boolean' &&
    'request_id' in error && typeof error.request_id === 'string' &&
    'details' in error && Array.isArray(error.details) && error.details.every(item => typeof item === 'string');
}

async function post<T>(path: string, body: unknown, timeout: number, signal?: AbortSignal): Promise<T> {
  const controller = new AbortController();
  let timedOut = false;
  const abort = () => controller.abort();
  signal?.addEventListener('abort', abort, { once: true });
  if (signal?.aborted) abort();
  const timer = setTimeout(() => { timedOut = true; controller.abort(); }, timeout);
  try {
    const response = await fetch('/api/v1' + path, {
      method: 'POST', headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify(body), signal: controller.signal,
    });
    let data: unknown;
    try { data = await response.json(); }
    catch { throw new ApiError('Сервер вернул некорректный ответ.', 'INVALID_RESPONSE', true, undefined, [], response.status); }
    if (!response.ok) {
      if (isErrorResponse(data)) {
        const error = data.error;
        throw new ApiError(error.message, error.code, error.retryable, error.request_id, error.details, response.status);
      }
      throw new ApiError('Ошибка сервера (HTTP ' + response.status + ').', 'INVALID_RESPONSE', true, undefined, [], response.status);
    }
    if (!data || typeof data !== 'object' || Array.isArray(data)) throw new ApiError('Пустой или некорректный ответ.', 'INVALID_RESPONSE', true);
    return data as T;
  } catch (error) {
    if (timedOut) throw new ApiError('Время ожидания истекло. Можно повторить запрос вручную. Сервер мог продолжить работу.', 'CLIENT_TIMEOUT', true);
    if (controller.signal.aborted) throw new ApiError('Ожидание прекращено. Это не отменяет работу сервера.', 'ABORTED', true);
    if (error instanceof ApiError) throw error;
    throw new ApiError('Не удалось связаться с сервером. Проверьте соединение и повторите вручную.', 'NETWORK_ERROR', true);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', abort);
  }
}

export const api = {
  createAnalysis: (request: AnalysisRequest, signal?: AbortSignal) => post<AnalysisResponse>('/analyses', request, ANALYSIS_TIMEOUT_MS, signal),
  createDiagnosis: (id: string, request: DiagnosisRequest, signal?: AbortSignal) => post<DiagnosisResponse>('/analyses/' + encodeURIComponent(id) + '/diagnoses', request, DIAGNOSIS_TIMEOUT_MS, signal),
};
