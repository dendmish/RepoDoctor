import { useState, type FormEvent } from 'react';
import type { DiagnosisRequest, DiagnosisResponse, TargetEnvironment } from '../api/types';
import { EvidenceLinks, EvidencePanel, EvidenceProvider } from './EvidencePanel';
import { confidenceLabels, GenerationNotice } from './ReportSections';
import { RunSteps, TextList } from './RunPlanView';

export function ErrorLogForm({ busy, target, initialUseAI, onSubmit }: {
  busy: boolean; target: TargetEnvironment; initialUseAI: boolean; onSubmit: (request: DiagnosisRequest) => void;
}) {
  const [log, setLog] = useState('');
  const [command, setCommand] = useState('');
  const [useAI, setUseAI] = useState(initialUseAI);
  const [validation, setValidation] = useState('');
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    if (!log.trim() || log.length > 30_000 || command.length > 2000) {
      setValidation('Вставьте непустой лог до 30 000 символов; команда — до 2 000 символов.'); return;
    }
    setValidation('');
    onSubmit({ log, command: command.trim() ? command : null, use_ai: useAI });
  }
  return <form onSubmit={submit} aria-label="Диагностика ошибки">
    <fieldset disabled={busy}><legend>Разобрать ошибку запуска</legend>
      <p>Окружение текущего анализа: <strong>{target.os} / {target.shell}</strong></p>
      <p className="notice" id="log-privacy">Перед отправкой удалите ключи и личные данные. Автоматическая маскировка не гарантирует полного удаления секретов. Лог хранится только в памяти этой страницы.</p>
      <label htmlFor="error-log">Лог ошибки</label>
      <textarea id="error-log" required maxLength={30_000} rows={9} value={log} spellCheck={false}
        aria-describedby="log-privacy log-count" onChange={event => { setLog(event.target.value); setValidation(''); }} />
      <small id="log-count">{log.length} / 30 000 символов</small>
      <label htmlFor="failed-command">Команда, вызвавшая ошибку (необязательно)</label>
      <input id="failed-command" maxLength={2000} value={command} onChange={event => setCommand(event.target.value)} />
      <small>{command.length} / 2 000 символов</small>
      <label className="checkbox"><input type="checkbox" checked={useAI} onChange={event => setUseAI(event.target.checked)} /> Использовать AI для диагностики</label>
      <small>Если включено, обработанный лог и фрагменты репозитория будут переданы внешней модели. До отправки формы текст не отправляется.</small>
      {validation && <p role="alert">{validation}</p>}
      <button type="submit" disabled={busy}>{busy ? 'Разбираем ошибку…' : 'Разобрать ошибку'}</button>
    </fieldset>
  </form>;
}

export function DiagnosisPanel({ data, synthetic }: { data: DiagnosisResponse; synthetic: boolean }) {
  return <EvidenceProvider items={data.evidence} prefix={`diagnosis-${data.diagnosis_id}`} synthetic={synthetic}>
    <section aria-label="Результат диагностики">
      <h3>Диагностика ошибки</h3><p>{data.summary}</p><GenerationNotice generation={data.generation} />
      <small>Создана: {data.created_at}</small>
      <p className="notice">Это вероятные причины и рекомендации. Исправления не выполнялись — проверьте результат самостоятельно.</p>
      <TextList items={data.warnings} />
      {!data.causes.length && <p>Для определения причины нужны дополнительные сведения.</p>}
      {data.causes.map(cause => <article className="cause" key={cause.id}>
        <h4>{cause.title}</h4><small>Уверенность: {confidenceLabels[cause.confidence]} · Источник вывода: {cause.origin}</small>
        <p>{cause.explanation}</p><EvidenceLinks ids={cause.evidence_ids} />
        <RunSteps steps={cause.fixes} />
        <p><strong>Проверка результата: </strong>{cause.verification}</p>
      </article>)}
      {!!data.questions.length && <><h4>Нужно уточнить</h4><TextList items={data.questions} /></>}
    </section>
    <EvidencePanel />
  </EvidenceProvider>;
}
