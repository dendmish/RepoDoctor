import { delay, http, HttpResponse } from 'msw';
import python from '../../../contracts/examples/analysis_python.json';
import node from '../../../contracts/examples/analysis_node.json';
import needsInput from '../../../contracts/examples/analysis_needs_input.json';
import diagnosis from '../../../contracts/examples/diagnosis_python.json';
import unknownDiagnosis from '../../../contracts/examples/diagnosis_unknown.json';
import invalid from '../../../contracts/examples/error_invalid_input.json';
import rateLimited from '../../../contracts/examples/error_rate_limited.json';
import notFound from '../../../contracts/examples/error_analysis_not_found.json';
import type { AnalysisResponse, DiagnosisResponse, ErrorResponse } from '../api/types';

// JSON imports widen enum literals; these assertions reference generated DTOs only.
// Backend contract tests validate the normative example contents.
export const examples = {
  python: python as AnalysisResponse, node: node as AnalysisResponse,
  needsInput: needsInput as AnalysisResponse, diagnosis: diagnosis as DiagnosisResponse,
  invalid: invalid as ErrorResponse, rateLimited: rateLimited as ErrorResponse,
  unknownDiagnosis: unknownDiagnosis as DiagnosisResponse, notFound: notFound as ErrorResponse,
};
export const scenarios = ['python', 'node', 'needs_input', 'invalid', 'rate_limited', 'network',
  'diagnosis_fallback', 'diagnosis_unknown', 'analysis_expired', 'diagnosis_busy', 'diagnosis_network'] as const;
export type Scenario = typeof scenarios[number];

export function createHandlers(scenario: Scenario = 'python', latency = 400) {
  return [
    http.post('/api/v1/analyses', async () => {
      await delay(latency);
      if (scenario === 'network') return HttpResponse.error();
      if (scenario === 'invalid') return HttpResponse.json(invalid, { status: 422 });
      if (scenario === 'rate_limited') return HttpResponse.json(rateLimited, { status: 429 });
      const result = scenario === 'node' ? node : scenario === 'needs_input' ? needsInput : python;
      return HttpResponse.json(result, { status: 201 });
    }),
    http.post('/api/v1/analyses/:id/diagnoses', async ({ params }) => {
      await delay(latency);
      if (params.id !== diagnosis.analysis_id) return HttpResponse.json(notFound, { status: 404 });
      if (scenario === 'analysis_expired') return HttpResponse.json(notFound, { status: 404 });
      if (scenario === 'diagnosis_network') return HttpResponse.error();
      if (scenario === 'diagnosis_busy') return HttpResponse.json({ error: {
        code: 'SERVER_BUSY', message: 'Сервер занят.', retryable: true, details: [], request_id: 'synthetic-busy',
      } }, { status: 429 });
      if (scenario === 'diagnosis_fallback' || scenario === 'diagnosis_unknown') return HttpResponse.json({
        ...unknownDiagnosis, analysis_id: diagnosis.analysis_id,
        generation: { ...unknownDiagnosis.generation, mode: 'fallback', model: null,
          reason: scenario === 'diagnosis_fallback' ? 'ai_timeout' : 'disabled_by_user' },
        questions: unknownDiagnosis.questions.map(question => question.replace('node --version', 'python --version')),
        warnings: ['Синтетический MSW-сценарий; AI не вызывался.', 'Использованы локальные правила.'],
      });
      return HttpResponse.json(diagnosis);
    }),
  ];
}
