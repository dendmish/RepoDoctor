import type { AnalysisResponse, Finding, GenerationInfo } from '../api/types';
import { safeGithubURL } from '../lib/evidence';
import { EvidenceLinks } from './EvidencePanel';
import { TextList } from './RunPlanView';

export const confidenceLabels = { low: 'низкая', medium: 'средняя', high: 'высокая' };
export const severityLabels = { info: 'Информация', warning: 'Предупреждение', blocker: 'Препятствие' };

export function GenerationNotice({ generation }: { generation: GenerationInfo }) {
  return <div className="generation">
    <p>Режим генерации: <strong>{generation.mode}</strong>{generation.mode === 'fallback' && ' — локальные правила'}</p>
    {generation.reason && <p>Причина: {generation.reason}</p>}
    {generation.model && <small>Модель: {generation.model}</small>}
    <small>Версия промпта: {generation.prompt_version}</small>
  </div>;
}

export function SummaryCard({ data }: { data: AnalysisResponse }) {
  const url = data.source_mode === 'github' ? safeGithubURL(data.repository.url) : null;
  return <section aria-label="Сведения о репозитории" className="summary-card">
    <p className="eyebrow">ОТЧЁТ О РЕПОЗИТОРИИ</p><h2>{data.repository.name}</h2>
    <p role="status">Ответ получен</p>
    <p>{url ? <a href={url} target="_blank" rel="noopener noreferrer">{data.repository.url}</a> : data.repository.url}</p>
    {data.repository.description && <p>{data.repository.description}</p>}
    <p className="provenance">Источник: {data.source_mode} · Генерация: {data.generation.mode}</p>
    {data.source_mode === 'fixture' && <p className="notice">Синтетический локальный пример; загрузка GitHub не подтверждается этим отчётом.</p>}
    <dl className="metadata">
      <dt>Commit SHA</dt><dd><code>{data.repository.resolved_commit}</code></dd>
      <dt>Окружение</dt><dd>{data.target.os} / {data.target.shell}</dd>
      <dt>Стек</dt><dd>{data.facts.stack}</dd>
      <dt>Ветка по умолчанию</dt><dd>{data.repository.default_branch}</dd>
      <dt>Создан</dt><dd>{data.created_at}</dd>
      <dt>Контекст доступен до</dt><dd>{data.expires_at}</dd>
    </dl>
    <GenerationNotice generation={data.generation} />
    {!!data.warnings.length && <div className="warnings"><h3>Ограничения и замечания</h3><TextList items={data.warnings} /></div>}
  </section>;
}

export function CoverageNotice({ coverage }: { coverage: AnalysisResponse['coverage'] }) {
  return <section aria-label="Полнота анализа">
    <h3>Полнота анализа: {coverage.status}</h3>
    {coverage.status === 'partial' && <p className="notice">Анализ частичный: учитывайте пропущенные файлы и ограничения.</p>}
    <p>Прочитано файлов: {coverage.files_read} из {coverage.files_selected} выбранных. Наблюдаемых записей дерева: {coverage.tree_entries_seen}. Объём: {coverage.bytes_read} байт.</p>
    <small>complete означает завершение ограниченной выборки; это не чтение всего репозитория.</small>
    <TextList items={coverage.limitations} />
  </section>;
}

export function FactsPanel({ facts }: { facts: AnalysisResponse['facts'] }) {
  return <section aria-label="Структура и зависимости">
    <h3>Структура и зависимости</h3>
    <h4>Подпроекты и manifests</h4>
    {!facts.project_roots.length && <p>Корни проектов не определены.</p>}
    <ul>{facts.project_roots.map(root => <li key={root.path}><strong>{root.path}</strong> · {root.stack}<TextList items={root.manifest_paths} /></li>)}</ul>
    <h4>Runtime</h4>
    {!facts.runtime_hints.length && <p>Версия runtime не определена.</p>}
    <ul>{facts.runtime_hints.map((hint, i) => <li key={i}>{hint.runtime}: {hint.constraint}<EvidenceLinks ids={hint.evidence_ids} /></li>)}</ul>
    <h4>Менеджеры пакетов</h4>
    {!facts.package_managers.length && <p>Менеджер не определён.</p>}
    <ul>{facts.package_managers.map((hint, i) => <li key={i}>{hint.name} · папка {hint.root}<EvidenceLinks ids={hint.evidence_ids} /></li>)}</ul>
    <details className="dependencies"><summary>Зависимости ({facts.dependencies.length})</summary>
      <div className="table-scroll"><table><caption>Заявленные зависимости из manifests</caption>
        <thead><tr><th>Пакет</th><th>Ограничение</th><th>Стек / тип</th><th>Manifest и источники</th></tr></thead>
        <tbody>{facts.dependencies.map((dep, i) => <tr key={i}><td>{dep.name}</td><td>{dep.constraint ?? 'не задано'}</td><td>{dep.ecosystem} / {dep.kind}</td><td>{dep.manifest_path}<EvidenceLinks ids={dep.evidence_ids} /></td></tr>)}</tbody>
      </table></div>{!facts.dependencies.length && <p>Зависимости не извлечены.</p>}
    </details>
    <h4>Точки входа</h4><ul>{facts.entrypoints.map((entry, i) => <li key={i}><code>{entry.command_hint}</code> · {entry.root} ({entry.kind})<EvidenceLinks ids={entry.evidence_ids} /></li>)}</ul>
    {!facts.entrypoints.length && <p>Подтверждённая точка входа не определена.</p>}
    {!!facts.env_var_names.length && <><h4>Переменные окружения (только имена)</h4><TextList items={facts.env_var_names} /></>}
    {!!facts.data_hints.length && <><h4>Данные и модели</h4><TextList items={facts.data_hints} /></>}
    {!!facts.gpu_hints.length && <><h4>GPU / CUDA — требуется проверка</h4><TextList items={facts.gpu_hints} /></>}
  </section>;
}

export function FindingsList({ findings }: { findings: Finding[] }) {
  return <section aria-label="Потенциальные проблемы"><h3>Потенциальные проблемы</h3>
    {!findings.length && <p>В полученном отчёте нет находок. Это не гарантирует успешный запуск.</p>}
    <ul className="findings">{findings.map(finding => <li key={finding.id} className={`finding severity-${finding.severity}`}>
      <p className="badge">{severityLabels[finding.severity]}</p><h4>{finding.title}</h4><p>{finding.description}</p>
      <small>Уверенность: {confidenceLabels[finding.confidence]} · Источник вывода: {finding.origin} · {finding.rule_id}</small>
      <p><strong>Рекомендация: </strong>{finding.suggested_action}</p><EvidenceLinks ids={finding.evidence_ids} />
    </li>)}</ul>
  </section>;
}
