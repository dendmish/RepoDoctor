import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError } from '../api/client';
import type { DiagnosisRequest, DiagnosisResponse } from '../api/types';

type State = { status: 'idle' } | { status: 'submitting' } |
  { status: 'success'; data: DiagnosisResponse } | { status: 'error'; error: ApiError };

export function useDiagnosis(analysisId: string) {
  const [state, setState] = useState<State>({ status: 'idle' });
  const sequence = useRef(0);
  const active = useRef<AbortController | null>(null);
  const currentId = useRef(analysisId);
  const lastRequest = useRef<DiagnosisRequest | null>(null);
  currentId.current = analysisId;
  useEffect(() => {
    sequence.current++;
    active.current?.abort(); active.current = null; lastRequest.current = null;
    setState({ status: 'idle' });
    return () => { sequence.current++; active.current?.abort(); active.current = null; lastRequest.current = null; };
  }, [analysisId]);
  const cancel = useCallback(() => {
    sequence.current++; active.current?.abort(); active.current = null;
    setState({ status: 'idle' });
  }, []);
  const submit = useCallback(async (request: DiagnosisRequest) => {
    if (active.current) return;
    const controller = new AbortController();
    active.current = controller; lastRequest.current = { ...request };
    const current = ++sequence.current;
    setState({ status: 'submitting' });
    try {
      const data = await api.createDiagnosis(analysisId, request, controller.signal);
      if (data.analysis_id !== analysisId) throw new ApiError('Диагноз относится к другому анализу.', 'INVALID_RESPONSE', true);
      if (currentId.current === analysisId && sequence.current === current) setState({ status: 'success', data });
    } catch (error) {
      if (currentId.current === analysisId && sequence.current === current) setState({
        status: 'error', error: error instanceof ApiError ? error : new ApiError('Не удалось получить диагноз.', 'UNKNOWN_ERROR', true),
      });
    } finally {
      if (currentId.current === analysisId && sequence.current === current) active.current = null;
    }
  }, [analysisId]);
  const retry = useCallback(() => { if (lastRequest.current) void submit(lastRequest.current); }, [submit]);
  return { state, submit, retry, cancel };
}
