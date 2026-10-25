import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { expect, it, vi } from 'vitest';
import App from '../src/App';
import { api, ApiError } from '../src/api/client';
import type { DiagnosisResponse } from '../src/api/types';
import { AnalysisReport } from '../src/components/AnalysisReport';
import { examples, createHandlers } from '../src/mocks/handlers';
import * as exporter from '../src/lib/exportMarkdown';
import { server } from './setup';

function renderReport() {
  return render(<AnalysisReport data={examples.python} initialUseAI={true} onReanalyze={vi.fn()} />);
}
async function enterLog(text = "ModuleNotFoundError: No module named 'dotenv'") {
  const user = userEvent.setup();
  fireEvent.change(screen.getByLabelText('Лог ошибки'), { target: { value: text } });
  return user;
}
const submit = () => screen.getByRole('button', { name: 'Разобрать ошибку' });

it('sends only on submit, uses captured analysis ID, target and explicit AI opt-out', async () => {
  let payload: unknown, id: unknown;
  server.use(http.post('/api/v1/analyses/:id/diagnoses', async ({ params, request }) => {
    payload = await request.json(); id = params.id;
    return HttpResponse.json(examples.diagnosis);
  }));
  const send = vi.spyOn(api, 'createDiagnosis');
  renderReport();
  const user = await enterLog();
  await user.type(screen.getByLabelText(/Команда, вызвавшая/), 'python -m demo_cli');
  await user.click(screen.getByLabelText('Использовать AI для диагностики'));
  expect(send).not.toHaveBeenCalled();
  await user.click(submit());
  expect(await screen.findByRole('region', { name: 'Результат диагностики' })).toHaveTextContent(examples.diagnosis.summary);
  expect(id).toBe(examples.python.analysis_id);
  expect(payload).toEqual({ log: "ModuleNotFoundError: No module named 'dotenv'", command: 'python -m demo_cli', use_ai: false });
  expect(send).toHaveBeenCalledOnce();
});

it('rejects whitespace-only and oversized input without calling API', async () => {
  const send = vi.spyOn(api, 'createDiagnosis');
  renderReport();
  const user = await enterLog('   \n');
  await user.click(submit());
  expect(screen.getByRole('alert')).toHaveTextContent('непустой лог');
  fireEvent.change(screen.getByLabelText('Лог ошибки'), { target: { value: 'x'.repeat(30_001) } });
  fireEvent.submit(screen.getByRole('form', { name: 'Диагностика ошибки' }));
  expect(send).not.toHaveBeenCalled();
  expect(screen.getByLabelText('Лог ошибки')).toHaveAttribute('maxlength', '30000');
  expect(screen.getByLabelText(/Команда, вызвавшая/)).toHaveAttribute('maxlength', '2000');
});

it('blocks duplicate diagnosis submissions and accepts only matching analysis responses', async () => {
  let finish!: (value: DiagnosisResponse) => void;
  const send = vi.spyOn(api, 'createDiagnosis').mockReturnValue(new Promise(resolve => { finish = resolve; }));
  renderReport();
  const user = await enterLog();
  await user.dblClick(submit());
  expect(screen.getByRole('button', { name: 'Разбираем ошибку…' })).toBeDisabled();
  fireEvent.submit(screen.getByRole('form', { name: 'Диагностика ошибки' }));
  expect(send).toHaveBeenCalledOnce();
  await act(async () => finish({ ...examples.diagnosis, analysis_id: 'another-analysis' }));
  expect(screen.getByRole('alert')).toHaveTextContent('INVALID_RESPONSE');
  expect(screen.queryByRole('region', { name: 'Результат диагностики' })).not.toBeInTheDocument();
});

it.each(['diagnosis_fallback', 'diagnosis_unknown'] as const)('shows %s with questions and mode/reason', async scenario => {
  server.use(...createHandlers(scenario, 0));
  renderReport();
  const user = await enterLog('unrecognized error');
  await user.click(submit());
  const result = await screen.findByRole('region', { name: 'Результат диагностики' });
  expect(result).toHaveTextContent('fallback');
  expect(result).toHaveTextContent(scenario === 'diagnosis_fallback' ? 'ai_timeout' : 'disabled_by_user');
  expect(result).toHaveTextContent('Нужно уточнить');
});

it.each(['SERVER_BUSY', 'CLIENT_TIMEOUT', 'NETWORK_ERROR'] as const)('offers manual retry for %s without automatic POST', async code => {
  const send = vi.spyOn(api, 'createDiagnosis')
    .mockRejectedValueOnce(new ApiError('Ошибка ожидания', code, true, 'request-test'))
    .mockResolvedValueOnce(examples.diagnosis);
  renderReport();
  const user = await enterLog();
  await user.click(submit());
  expect(await screen.findByRole('alert')).toHaveTextContent('request-test');
  expect(send).toHaveBeenCalledOnce();
  await user.click(screen.getByRole('button', { name: 'Повторить запрос' }));
  expect(await screen.findByRole('region', { name: 'Результат диагностики' })).toBeVisible();
  expect(send).toHaveBeenCalledTimes(2);
  expect(send.mock.calls[1][1]).toEqual(send.mock.calls[0][1]);
});

it('handles expired context with explicit reanalysis and clears raw input/diagnosis', async () => {
  server.use(...createHandlers('analysis_expired', 0));
  const analysis = vi.spyOn(api, 'createAnalysis').mockResolvedValue(examples.python);
  render(<App />);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText('URL публичного GitHub-репозитория'), examples.python.repository.url);
  await user.click(screen.getByRole('button', { name: 'Анализировать' }));
  await screen.findByLabelText('Лог ошибки');
  fireEvent.change(screen.getByLabelText('Лог ошибки'), { target: { value: 'PRIVATE_RAW_INPUT' } });
  await user.click(submit());
  expect(await screen.findByRole('alert')).toHaveTextContent('Контекст анализа истёк');
  expect(analysis).toHaveBeenCalledOnce();
  await user.click(screen.getByRole('button', { name: 'Повторить анализ репозитория' }));
  expect(await screen.findByLabelText('Лог ошибки')).toHaveValue('');
  expect(analysis).toHaveBeenCalledTimes(2);
});

it.each(['resolve', 'reject'] as const)('drops late diagnosis %s when analysis changes', async outcome => {
  let finish!: (value: DiagnosisResponse) => void;
  let fail!: (value: Error) => void;
  const send = vi.spyOn(api, 'createDiagnosis').mockReturnValue(new Promise((resolve, reject) => { finish = resolve; fail = reject; }));
  vi.spyOn(api, 'createAnalysis').mockResolvedValueOnce(examples.python).mockResolvedValueOnce(examples.node);
  render(<App />);
  const user = userEvent.setup();
  await user.type(screen.getByLabelText('URL публичного GitHub-репозитория'), examples.python.repository.url);
  await user.click(screen.getByRole('button', { name: 'Анализировать' }));
  await screen.findByLabelText('Лог ошибки');
  fireEvent.change(screen.getByLabelText('Лог ошибки'), { target: { value: 'OLD_RAW_LOG' } });
  await user.click(submit());
  await user.click(screen.getByRole('button', { name: 'Анализировать' }));
  await screen.findByRole('heading', { name: 'node-api-demo' });
  expect(send.mock.calls[0][2]?.aborted).toBe(true);
  expect(screen.getByLabelText('Лог ошибки')).toHaveValue('');
  await act(async () => outcome === 'resolve' ? finish(examples.diagnosis) : fail(new Error('old')));
  expect(screen.queryByRole('region', { name: 'Результат диагностики' })).not.toBeInTheDocument();
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
});

it('exports the current safe diagnosis, never raw form log/command or persistence', async () => {
  const download = vi.spyOn(exporter, 'downloadReport').mockImplementation(() => {});
  const local = vi.spyOn(Storage.prototype, 'setItem');
  renderReport();
  const user = await enterLog('RAW_LOG_SECRET_SENTINEL');
  await user.type(screen.getByLabelText(/Команда, вызвавшая/), 'RAW_COMMAND_SECRET_SENTINEL');
  await user.click(submit());
  await screen.findByRole('region', { name: 'Результат диагностики' });
  await user.click(screen.getByRole('button', { name: 'Скачать Markdown' }));
  const markdown = download.mock.calls[0][0];
  expect(markdown).toContain(examples.diagnosis.summary);
  expect(markdown).not.toContain('RAW_LOG_SECRET_SENTINEL');
  expect(markdown).not.toContain('RAW_COMMAND_SECRET_SENTINEL');
  expect(local).not.toHaveBeenCalled();
});

it.each(['diagnosis_busy', 'diagnosis_network'] as const)('handles actual MSW %s failures', async scenario => {
  server.use(...createHandlers(scenario, 0));
  const send = vi.spyOn(api, 'createDiagnosis');
  renderReport();
  const user = await enterLog();
  await user.click(submit());
  expect(await screen.findByRole('alert')).toHaveTextContent(scenario === 'diagnosis_busy' ? 'SERVER_BUSY' : 'NETWORK_ERROR');
  expect(send).toHaveBeenCalledOnce();
  expect(screen.getByRole('button', { name: 'Повторить запрос' })).toBeVisible();
});

it('shows non-retryable validation details as inert text', async () => {
  vi.spyOn(api, 'createDiagnosis').mockRejectedValue(new ApiError('Проверьте лог', 'INVALID_INPUT', false, 'validation-id', ['<img src=x onerror=alert(1)>']));
  const { container } = renderReport();
  const user = await enterLog();
  await user.click(submit());
  expect(await screen.findByRole('alert')).toHaveTextContent('<img src=x onerror=alert(1)>');
  expect(container.querySelector('img')).toBeNull();
  expect(screen.queryByRole('button', { name: 'Повторить запрос' })).not.toBeInTheDocument();
});
