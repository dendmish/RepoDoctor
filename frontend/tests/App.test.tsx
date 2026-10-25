import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import App from '../src/App';
import { api } from '../src/api/client';
import type { AnalysisResponse } from '../src/api/types';
import { examples, createHandlers } from '../src/mocks/handlers';
import { server } from './setup';

async function fill() {
  const user = userEvent.setup();
  await user.type(screen.getByLabelText('URL публичного GitHub-репозитория'), 'https://github.com/owner/repo');
  return user;
}
const button = () => screen.getByRole('button', { name: 'Анализировать' });

describe('analysis form', () => {
  it('requires a URL before sending', async () => {
    const send = vi.spyOn(api, 'createAnalysis');
    render(<App />);
    await userEvent.click(button());
    expect(screen.getByLabelText('URL публичного GitHub-репозитория')).toBeInvalid();
    expect(send).not.toHaveBeenCalled();
  });
  it.each([['windows', 'powershell'], ['linux', 'bash'], ['macos', 'zsh']])('pairs %s with %s and sends the exact payload', async (os, shell) => {
    let payload: unknown;
    server.use(http.post('/api/v1/analyses', async ({ request }) => {
      expect(request.headers.get('content-type')).toBe('application/json');
      payload = await request.json();
      return HttpResponse.json(examples.python, { status: 201 });
    }));
    render(<App />);
    const user = await fill();
    await user.selectOptions(screen.getByLabelText('Операционная система'), os);
    expect(screen.getByLabelText('Shell')).toHaveValue(shell);
    expect(screen.getByLabelText('Shell')).toBeDisabled();
    await user.type(screen.getByLabelText(/Ветка, тег/), ' release/v1 ');
    await user.click(screen.getByLabelText('Использовать AI'));
    await user.click(button());
    await screen.findByText('Ответ получен');
    expect(payload).toEqual({ repo_url: 'https://github.com/owner/repo', ref: 'release/v1', target: { os, shell }, use_ai: false });
  });
  it('sends null ref and use_ai=true by default; prevents duplicate submission', async () => {
    let finish!: (response: AnalysisResponse) => void;
    const send = vi.spyOn(api, 'createAnalysis').mockReturnValue(new Promise(resolve => { finish = resolve; }));
    render(<App />);
    const user = await fill();
    await user.dblClick(button());
    expect(screen.getByRole('button', { name: 'Анализируем…' })).toBeDisabled();
    fireEvent.submit(screen.getByRole('form'));
    expect(send).toHaveBeenCalledTimes(1);
    expect(send.mock.calls[0][0]).toMatchObject({ ref: null, use_ai: true });
    expect(screen.getByRole('status')).toHaveTextContent('до 100 секунд');
    await act(async () => finish(examples.python));
    expect(await screen.findByText('Ответ получен')).toBeVisible();
  });
  it('shows a contract error and permits manual resubmit without automatic retries', async () => {
    server.use(...createHandlers('rate_limited', 0));
    const send = vi.spyOn(api, 'createAnalysis');
    render(<App />);
    const user = await fill();
    await user.click(button());
    expect(await screen.findByRole('alert')).toHaveTextContent(examples.rateLimited.error.request_id);
    expect(send).toHaveBeenCalledTimes(1);
    server.use(...createHandlers('node', 0));
    await user.click(button());
    expect(await screen.findByRole('heading', { name: 'node-api-demo' })).toBeVisible();
    expect(screen.getByText(/Генерация: fallback/)).toBeVisible();
    expect(send).toHaveBeenCalledTimes(2);
  });
  it.each(['resolve', 'reject'])('ignores an old %s after cancel and a new result', async outcome => {
    let finish!: (value: AnalysisResponse) => void;
    let fail!: (reason: Error) => void;
    const send = vi.spyOn(api, 'createAnalysis')
      .mockImplementationOnce(() => new Promise((resolve, reject) => { finish = resolve; fail = reject; }))
      .mockResolvedValueOnce(examples.node);
    render(<App />);
    const user = await fill();
    await user.click(button());
    await user.click(screen.getByRole('button', { name: 'Прекратить ожидание' }));
    expect(send.mock.calls[0][1]?.aborted).toBe(true);
    await user.click(button());
    await screen.findByRole('heading', { name: 'node-api-demo' });
    await act(async () => outcome === 'resolve' ? finish(examples.python) : fail(new Error('old')));
    expect(screen.getByRole('heading', { name: 'node-api-demo' })).toBeVisible();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
  it('aborts waiting on unmount', async () => {
    const send = vi.spyOn(api, 'createAnalysis').mockImplementation(() => new Promise(() => {}));
    const { unmount } = render(<App />);
    const user = await fill();
    await user.click(button());
    unmount();
    await waitFor(() => expect(send.mock.calls[0][1]?.aborted).toBe(true));
  });
});


it('offers manual resubmit after timeout and shows a needs-input response', async () => {
  const { ApiError } = await import('../src/api/client');
  const send = vi.spyOn(api, 'createAnalysis')
    .mockRejectedValueOnce(new ApiError('Время ожидания истекло. Сервер мог продолжить работу.', 'CLIENT_TIMEOUT', true))
    .mockResolvedValueOnce(examples.needsInput);
  render(<App />);
  const user = await fill();
  await user.click(button());
  expect(await screen.findByRole('alert')).toHaveTextContent('CLIENT_TIMEOUT');
  expect(send).toHaveBeenCalledTimes(1);
  await user.click(button());
  expect(await screen.findByText(examples.needsInput.run_plan.summary)).toBeVisible();
  expect(send).toHaveBeenCalledTimes(2);
});
