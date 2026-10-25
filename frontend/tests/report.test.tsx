import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it, vi } from 'vitest';
import { AnalysisReport } from '../src/components/AnalysisReport';
import { CommandBlock } from '../src/components/CommandBlock';
import { examples } from '../src/mocks/handlers';
import { safeGithubURL } from '../src/lib/evidence';
import * as exporter from '../src/lib/exportMarkdown';

it('renders metadata, coverage, findings, prerequisites, commands and assumptions', () => {
  render(<AnalysisReport data={examples.python} initialUseAI={false} onReanalyze={vi.fn()} />);
  expect(screen.getByText(examples.python.repository.resolved_commit)).toBeVisible();
  expect(screen.getByRole('region', { name: 'Полнота анализа' })).toHaveTextContent('complete');
  expect(screen.getByRole('region', { name: 'Структура и зависимости' })).toHaveTextContent('requirements.txt');
  expect(screen.getByRole('region', { name: 'План запуска' })).toHaveTextContent('Предварительные условия');
  expect(screen.getAllByText(/Shell:/).length).toBeGreaterThan(0);
  expect(screen.getAllByRole('button', { name: 'Скопировать команду' }).length).toBeGreaterThan(0);
  expect(screen.getByLabelText('Использовать AI для диагностики')).not.toBeChecked();
});

it('shows partial coverage, fallback and questions before any run steps', () => {
  render(<AnalysisReport data={examples.needsInput} initialUseAI={false} onReanalyze={vi.fn()} />);
  const coverage = screen.getByRole('region', { name: 'Полнота анализа' });
  expect(coverage).toHaveTextContent('Анализ частичный');
  expect(coverage).toHaveTextContent(examples.needsInput.coverage.limitations[0]);
  const plan = screen.getByRole('region', { name: 'План запуска' });
  expect(plan).toHaveTextContent('Нужно уточнение перед запуском');
  expect(plan).toHaveTextContent(examples.needsInput.run_plan.questions[0]);
  expect(screen.getByText(/Источник: fixture · Генерация: fallback/)).toBeVisible();
});

it('opens the actual evidence and suppresses fake GitHub links in fixtures', async () => {
  const user = userEvent.setup();
  render(<AnalysisReport data={examples.python} initialUseAI={true} onReanalyze={vi.fn()} />);
  const refs = screen.getAllByRole('link').filter(link => link.getAttribute('href')?.startsWith('#'));
  expect(refs.length).toBeGreaterThan(0);
  await user.click(refs[0]);
  const id = refs[0].getAttribute('href')!.slice(1);
  expect(document.getElementById(id)).toHaveAttribute('open');
  expect(document.activeElement?.id).toBe(id);
  expect(screen.queryByRole('link', { name: 'Открыть источник в GitHub' })).not.toBeInTheDocument();
});

it('shows missing evidence as a defect, renders HTML as text and rejects unsafe links', () => {
  const data = structuredClone(examples.python);
  data.source_mode = 'github';
  data.run_plan.summary = '<img src=x onerror=alert(1)>';
  data.evidence[0].excerpt = '<script>window.hacked = true</script>';
  data.evidence[0].url = 'https://github.com.evil.invalid/malicious';
  data.findings[0].evidence_ids.push('missing-id');
  const { container } = render(<AnalysisReport data={data} initialUseAI={true} onReanalyze={vi.fn()} />);
  expect(screen.getByText('Источник недоступен: missing-id')).toBeVisible();
  expect(screen.getByText(data.run_plan.summary)).toBeVisible();
  expect(container.querySelector('img, script')).toBeNull();
  expect(container.querySelector('a[href*="evil.invalid"]')).toBeNull();
  const link = screen.getAllByRole('link', { name: 'Открыть источник в GitHub' })[0];
  expect(link).toHaveAttribute('rel', 'noopener noreferrer');
  expect(link).toHaveAttribute('target', '_blank');
});

it.each(['javascript:alert(1)', 'http://github.com/a/b', 'https://github.com@evil.invalid/a', 'https://user:secret@github.com/a', 'https://github.com:8443/a', 'broken'])('rejects unsafe source URL %s', value => {
  expect(safeGithubURL(value)).toBeNull();
});

it.each([true, false])('copies commands with success=%s feedback', async success => {
  const user = userEvent.setup();
  const clipboard = vi.spyOn(navigator.clipboard, 'writeText');
  if (success) clipboard.mockResolvedValue(); else clipboard.mockRejectedValue(new Error('denied'));
  const command = examples.python.run_plan.steps.flatMap(step => step.commands)[0];
  render(<CommandBlock command={command} />);
  await user.click(screen.getByRole('button', { name: 'Скопировать команду' }));
  expect(clipboard).toHaveBeenCalledWith(command.text);
  expect(screen.getByRole('status')).toHaveTextContent(success ? 'Команда скопирована' : 'скопируйте вручную');
});

it('reports download failures and permits another export', async () => {
  const user = userEvent.setup();
  const download = vi.spyOn(exporter, 'downloadReport').mockImplementationOnce(() => { throw new Error('unavailable'); }).mockImplementation(() => {});
  render(<AnalysisReport data={examples.python} initialUseAI={true} onReanalyze={vi.fn()} />);
  await user.click(screen.getByRole('button', { name: 'Скачать Markdown' }));
  expect(screen.getByRole('alert')).toHaveTextContent('Не удалось скачать');
  await user.click(screen.getByRole('button', { name: 'Скачать Markdown' }));
  expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  expect(download).toHaveBeenCalledTimes(2);
});
