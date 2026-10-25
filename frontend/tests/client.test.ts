import { expect, it, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import { api, ANALYSIS_TIMEOUT_MS, DIAGNOSIS_TIMEOUT_MS } from '../src/api/client';
import { examples } from '../src/mocks/handlers';
import { server } from './setup';
import request from '../../contracts/examples/request_analysis.json';
import type { AnalysisRequest } from '../src/api/types';

it('posts diagnosis to the encoded path and parses the response', async () => {
  let body: unknown;
  server.use(http.post('/api/v1/analyses/:id/diagnoses', async ({ request, params }) => {
    expect(params.id).toBe('test/id');
    body = await request.json();
    return HttpResponse.json(examples.diagnosis);
  }));
  expect(await api.createDiagnosis('test/id', { log: 'error', use_ai: false })).toEqual(examples.diagnosis);
  expect(body).toEqual({ log: 'error', use_ai: false });
});

it.each([true, false])('enforces the %s operation deadline without retry', async analysis => {
  vi.useFakeTimers();
  const fetch = vi.spyOn(globalThis, 'fetch').mockImplementation((_url, init) => new Promise((_resolve, reject) => {
    init?.signal?.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')));
  }));
  const result = analysis ? api.createAnalysis(request as AnalysisRequest) : api.createDiagnosis('id', { log: 'error', use_ai: false });
  const assertion = expect(result).rejects.toMatchObject({ code: 'CLIENT_TIMEOUT', retryable: true });
  await vi.advanceTimersByTimeAsync(analysis ? ANALYSIS_TIMEOUT_MS : DIAGNOSIS_TIMEOUT_MS);
  await assertion;
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(vi.getTimerCount()).toBe(0);
});

it('handles malformed error responses safely', async () => {
  server.use(http.post('/api/v1/analyses', () => new HttpResponse('<html>oops</html>', { status: 502 })));
  await expect(api.createAnalysis(request as AnalysisRequest)).rejects.toMatchObject({ code: 'INVALID_RESPONSE', status: 502 });
});
it('handles network errors', async () => {
  server.use(http.post('/api/v1/analyses', () => HttpResponse.error()));
  await expect(api.createAnalysis(request as AnalysisRequest)).rejects.toMatchObject({ code: 'NETWORK_ERROR' });
});
it('respects an already aborted signal', async () => {
  const controller = new AbortController();
  controller.abort();
  await expect(api.createAnalysis(request as AnalysisRequest, controller.signal)).rejects.toMatchObject({ code: 'ABORTED' });
});
