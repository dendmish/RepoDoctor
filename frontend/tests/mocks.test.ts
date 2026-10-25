import { expect, it } from 'vitest';
import { createHandlers, examples } from '../src/mocks/handlers';
import { server } from './setup';
import { api } from '../src/api/client';
import request from '../../contracts/examples/request_analysis.json';
import type { AnalysisRequest } from '../src/api/types';

it.each([
  ['python', examples.python],
  ['node', examples.node],
  ['needs_input', examples.needsInput],
] as const)('serves the unchanged normative %s example', async (scenario, response) => {
  server.use(...createHandlers(scenario, 0));
  expect(await api.createAnalysis(request as AnalysisRequest)).toEqual(response);
});
it('parses the non-retryable validation envelope', async () => {
  server.use(...createHandlers('invalid', 0));
  await expect(api.createAnalysis(request as AnalysisRequest)).rejects.toMatchObject({
    code: examples.invalid.error.code, retryable: false,
    details: examples.invalid.error.details, requestId: examples.invalid.error.request_id,
  });
});
