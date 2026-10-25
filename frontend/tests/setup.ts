import '@testing-library/jest-dom/vitest';
import { afterAll, afterEach, beforeAll, vi } from 'vitest';
import { cleanup } from '@testing-library/react';
import { setupServer } from 'msw/node';
import { createHandlers } from '../src/mocks/handlers';

export const server = setupServer(...createHandlers('python', 0));
beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => { cleanup(); server.resetHandlers(); vi.restoreAllMocks(); vi.useRealTimers(); });
afterAll(() => server.close());
