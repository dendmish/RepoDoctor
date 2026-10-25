import { expect, it, vi } from 'vitest';
import { examples } from '../src/mocks/handlers';
import { codeFence, downloadReport, escapeMarkdown, exportMarkdown, reportFilename } from '../src/lib/exportMarkdown';

it('exports complete metadata, modes, findings, plan, sources and diagnosis', () => {
  const markdown = exportMarkdown(examples.python, examples.diagnosis);
  for (const text of [examples.python.repository.resolved_commit, 'Источник: fixture', 'Генерация: ai', 'Полнота анализа', 'Структура и зависимости', 'Потенциальные проблемы', 'План запуска', 'Доказательства анализа', 'Диагностика', 'Доказательства диагностики', examples.diagnosis.summary]) {
    expect(markdown).toContain(text);
  }
  expect(markdown).toContain('Команды ещё не выполнялись');
  expect(markdown).not.toContain('[Открыть источник]'); // Synthetic source URLs stay inert.
  expect(reportFilename(examples.python)).toBe('repodoctor-repodoctor-fixtures-python-cli-demo.md');
});

it('preserves partial coverage, questions and fallback reasons', () => {
  const markdown = exportMarkdown(examples.needsInput);
  expect(markdown).toContain('partial');
  expect(markdown).toContain('needs_input');
  expect(markdown).toContain(escapeMarkdown(examples.needsInput.generation.reason!));
  expect(markdown).toContain(escapeMarkdown(examples.needsInput.run_plan.questions[0]));
});

it('uses fences longer than any embedded run and escapes untrusted HTML/Markdown', () => {
  const data = structuredClone(examples.python);
  data.run_plan.summary = '<img src="https://evil.invalid"> ![tracking](https://evil.invalid/image)';
  data.run_plan.steps[0].commands[0].text = 'echo "```"\n````\n<img src=x>';
  const markdown = exportMarkdown(data);
  expect(markdown).toContain('`````powershell\necho "```"\n````\n<img src=x>\n`````');
  expect(markdown).toContain('&lt;img');
  expect(markdown).toContain('\\!\\[tracking\\]\\(https://evil.invalid/image\\)');
  expect(codeFence('```')).toBe('````text\n```\n````');
});

it('prevents path traversal in filenames and rejects diagnosis from another analysis', () => {
  const data = structuredClone(examples.python);
  data.repository.owner = '../../CON\\other'; data.repository.name = '../x/y\\z:*?';
  const filename = reportFilename(data);
  expect(filename).toMatch(/^repodoctor-[a-zA-Z0-9._-]+-[a-zA-Z0-9._-]+\.md$/);
  expect(filename).not.toMatch(/[\\/:*?]/);
  expect(() => exportMarkdown(examples.node, examples.diagnosis)).toThrow('another analysis');
});

it('downloads a Markdown Blob and revokes its object URL', () => {
  vi.useFakeTimers();
  const create = vi.fn().mockReturnValue('blob:synthetic');
  const revoke = vi.fn();
  const originalCreate = Object.getOwnPropertyDescriptor(URL, 'createObjectURL');
  const originalRevoke = Object.getOwnPropertyDescriptor(URL, 'revokeObjectURL');
  Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: create });
  Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revoke });
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  try {
    downloadReport('# Report', 'repodoctor-demo.md');
    expect(create.mock.calls[0][0]).toBeInstanceOf(Blob);
    expect(create.mock.calls[0][0].type).toBe('text/markdown;charset=utf-8');
    expect(click).toHaveBeenCalledOnce();
    expect(document.querySelector('a[download]')).toBeNull();
    vi.runAllTimers();
    expect(revoke).toHaveBeenCalledWith('blob:synthetic');
  } finally {
    if (originalCreate) Object.defineProperty(URL, 'createObjectURL', originalCreate); else Reflect.deleteProperty(URL, 'createObjectURL');
    if (originalRevoke) Object.defineProperty(URL, 'revokeObjectURL', originalRevoke); else Reflect.deleteProperty(URL, 'revokeObjectURL');
  }
});
