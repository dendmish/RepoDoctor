import { setupWorker } from 'msw/browser';
import { createHandlers, scenarios, type Scenario } from './handlers';

export async function startMocks() {
  if (!import.meta.env.DEV || import.meta.env.VITE_ENABLE_MSW !== 'true') return;
  const scenario = import.meta.env.VITE_MSW_SCENARIO ?? 'python';
  if (!scenarios.includes(scenario as Scenario)) throw new Error('Unknown MSW scenario: ' + scenario);
  const worker = setupWorker(...createHandlers(scenario as Scenario));
  await worker.start({
    onUnhandledRequest(request, print) {
      if (new URL(request.url).pathname.startsWith('/api/')) print.error();
    },
  });
}
