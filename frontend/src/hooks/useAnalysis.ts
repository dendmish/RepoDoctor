import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError } from '../api/client';
import type { AnalysisRequest, AnalysisResponse } from '../api/types';

type State = { status: 'idle' } | { status: 'submitting' } |
  { status: 'success'; data: AnalysisResponse } | { status: 'error'; error: ApiError };

export function useAnalysis() {
  const [state, setState] = useState<State>({ status: 'idle' });
  const sequence = useRef(0);
  const active = useRef<AbortController | null>(null);
  const lastRequest = useRef<AnalysisRequest | null>(null);
  const cancel = useCallback(() => {
    sequence.current++;
    active.current?.abort();
    active.current = null;
    setState({ status: 'idle' });
  }, []);
  useEffect(() => () => { sequence.current++; active.current?.abort(); active.current = null; }, []);
  const submit = useCallback(async (request: AnalysisRequest) => {
    if (active.current) return;
    const controller = new AbortController();
    active.current = controller;
    lastRequest.current = { ...request, target: { ...request.target } };
    const current = ++sequence.current;
    setState({ status: 'submitting' });
    try {
      const data = await api.createAnalysis(request, controller.signal);
      if (sequence.current === current) setState({ status: 'success', data });
    } catch (error) {
      if (sequence.current === current) setState({ status: 'error', error: error instanceof ApiError ? error : new ApiError('Не удалось получить анализ.', 'UNKNOWN_ERROR', true) });
    } finally {
      if (sequence.current === current) active.current = null;
    }
  }, []);
  const retry = useCallback(() => { if (lastRequest.current) void submit(lastRequest.current); }, [submit]);
  return { state, submit, cancel, retry, lastRequest: lastRequest.current };
}
