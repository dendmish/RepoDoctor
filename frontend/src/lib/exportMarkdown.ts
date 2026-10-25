import type { AnalysisResponse, DiagnosisResponse, Evidence, GenerationInfo, RunStep } from '../api/types';
import { evidenceLabel, safeGithubURL } from './evidence';

// All prose comes from untrusted repository/model text. Keep HTML and Markdown inert.
export function escapeMarkdown(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/[\\`*_{}\[\]()#!|~]/g, '\\$&');
}

export function codeFence(value: string, language = 'text'): string {
  const longest = Math.max(0, ...[...value.matchAll(/`+/g)].map(match => match[0].length));
  const fence = '`'.repeat(Math.max(3, longest + 1));
  return `${fence}${language}\n${value}\n${fence}`;
}

function list(values: string[]): string {
  return values.map(value => '- ' + escapeMarkdown(value).replace(/\n/g, '\n  ')).join('\n');
}

function generation(value: GenerationInfo): string {
  return [
    `Генерация: ${value.mode}`, value.reason ? `Причина: ${escapeMarkdown(value.reason)}` : '',
    value.model ? `Модель: ${escapeMarkdown(value.model)}` : '', `Версия промпта: ${escapeMarkdown(value.prompt_version)}`,
  ].filter(Boolean).join('\n\n');
}

function steps(values: RunStep[]): string {
  return values.map((step, i) => [
    `#### ${i + 1}. ${escapeMarkdown(step.title)}`, escapeMarkdown(step.description),
    step.assumptions.length ? '**Допущения**\n\n' + list(step.assumptions) : '',
    ...step.commands.map(command => [
      `Shell: ${command.shell}. Папка: ${escapeMarkdown(command.cwd)}.`,
      codeFence(command.text, command.shell), escapeMarkdown(command.explanation),
      command.requires_review ? 'Проверьте команду перед выполнением.' : '',
    ].filter(Boolean).join('\n\n')),
    '**Проверка:** ' + escapeMarkdown(step.verification),
    step.evidence_ids.length ? 'Источники: ' + step.evidence_ids.map(escapeMarkdown).join(', ') : '',
  ].filter(Boolean).join('\n\n')).join('\n\n');
}

function sources(values: Evidence[], synthetic: boolean): string {
  return values.map(item => {
    const url = synthetic || item.source === 'log' ? null : safeGithubURL(item.url);
    const link = url ? `\n\n[Открыть источник](${url.replace(/\(/g, '%28').replace(/\)/g, '%29')})` : '';
    return `#### ${escapeMarkdown(item.id)} — ${escapeMarkdown(evidenceLabel(item))}\n\n` +
      `Тип: ${item.source}${synthetic ? '; synthetic fixture' : ''}\n\n${codeFence(item.excerpt)}${link}`;
  }).join('\n\n');
}

export function exportMarkdown(analysis: AnalysisResponse, diagnosis?: DiagnosisResponse): string {
  if (diagnosis && diagnosis.analysis_id !== analysis.analysis_id) throw new Error('Diagnosis belongs to another analysis');
  const { repository: repo, facts, coverage, run_plan: plan } = analysis;
  return [
    `# RepoDoctor: ${escapeMarkdown(repo.owner)}/${escapeMarkdown(repo.name)}`,
    `Репозиторий: ${escapeMarkdown(repo.url)}`,
    `Commit SHA: ${repo.resolved_commit}`, `Источник: ${analysis.source_mode}`,
    analysis.source_mode === 'fixture' ? 'Синтетический локальный пример; доступность GitHub не подтверждена.' : '',
    `Окружение: ${analysis.target.os} / ${analysis.target.shell}. Стек: ${facts.stack}.`,
    `Создан: ${analysis.created_at}. Контекст доступен до: ${analysis.expires_at}.`,
    generation(analysis.generation),
    '## Полнота анализа',
    `${coverage.status}; файлов прочитано ${coverage.files_read} из ${coverage.files_selected} выбранных; ` +
      `записей дерева ${coverage.tree_entries_seen}; ${coverage.bytes_read} байт.`,
    'complete означает завершённую ограниченную выборку, а не весь репозиторий.',
    list(coverage.limitations), list(analysis.warnings),
    '## Структура и зависимости',
    ...facts.project_roots.map(root => `### ${escapeMarkdown(root.path)} (${root.stack})\n\n${list(root.manifest_paths)}`),
    '### Runtime', list(facts.runtime_hints.map(hint => `${hint.runtime}: ${hint.constraint} [${hint.evidence_ids.join(', ')}]`)),
    '### Менеджеры пакетов', list(facts.package_managers.map(hint => `${hint.name}; папка ${hint.root} [${hint.evidence_ids.join(', ')}]`)),
    '### Зависимости', list(facts.dependencies.map(dep => `${dep.name} ${dep.constraint ?? ''}; ${dep.ecosystem}/${dep.kind}; ${dep.manifest_path} [${dep.evidence_ids.join(', ')}]`)),
    '### Точки входа', list(facts.entrypoints.map(entry => `${entry.command_hint}; папка ${entry.root} [${entry.evidence_ids.join(', ')}]`)),
    '### Переменные окружения (имена)', list(facts.env_var_names),
    '### Данные и GPU', list([...facts.data_hints, ...facts.gpu_hints]),
    '## Потенциальные проблемы',
    ...analysis.findings.map(finding => [
      `### ${escapeMarkdown(finding.title)}`, `${finding.severity}; ${finding.confidence}; ${finding.origin}; ${escapeMarkdown(finding.rule_id)}`,
      escapeMarkdown(finding.description), escapeMarkdown(finding.suggested_action),
      'Источники: ' + finding.evidence_ids.map(escapeMarkdown).join(', '),
    ].join('\n\n')),
    '## План запуска', escapeMarkdown(plan.summary), `Статус: ${plan.status}`,
    'Команды ещё не выполнялись. Проверьте их перед локальным запуском.',
    '`<repo>` — папка клонированного проекта; `.` — текущая папка шага.',
    '### Предварительные условия', list(plan.prerequisites),
    '### Вопросы и уточнения', list(plan.questions), steps(plan.steps),
    '## Доказательства анализа', sources(analysis.evidence, analysis.source_mode === 'fixture'),
    ...(diagnosis ? [
      '## Диагностика', `Создана: ${diagnosis.created_at}`, generation(diagnosis.generation),
      escapeMarkdown(diagnosis.summary), list(diagnosis.warnings),
      ...diagnosis.causes.map(cause => [
        `### ${escapeMarkdown(cause.title)}`, `${cause.confidence}; ${cause.origin}`,
        escapeMarkdown(cause.explanation), 'Источники: ' + cause.evidence_ids.map(escapeMarkdown).join(', '),
        steps(cause.fixes), '**Проверка:** ' + escapeMarkdown(cause.verification),
      ].join('\n\n')),
      '### Дополнительные вопросы', list(diagnosis.questions),
      '### Доказательства диагностики', sources(diagnosis.evidence, analysis.source_mode === 'fixture'),
    ] : []),
  ].filter(Boolean).join('\n\n') + '\n';
}

export function reportFilename(analysis: AnalysisResponse): string {
  const clean = (value: string) => value.normalize('NFKC').replace(/[^a-zA-Z0-9._-]+/g, '-')
    .replace(/^[.-]+|[.-]+$/g, '').slice(0, 70) || 'repository';
  return `repodoctor-${clean(analysis.repository.owner)}-${clean(analysis.repository.name)}.md`;
}

export function downloadReport(markdown: string, filename: string): void {
  const url = URL.createObjectURL(new Blob([markdown], { type: 'text/markdown;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url; link.download = filename;
  document.body.append(link);
  try { link.click(); }
  finally { link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000); }
}
