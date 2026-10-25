import type { AnalysisResponse, RunStep } from '../api/types';
import { CommandBlock } from './CommandBlock';
import { EvidenceLinks } from './EvidencePanel';

export function TextList({ items }: { items: string[] }) {
  return items.length ? <ul>{items.map((item, i) => <li key={i}>{item}</li>)}</ul> : null;
}

export function RunSteps({ steps }: { steps: RunStep[] }) {
  return <ol className="steps">{steps.map(step => <li key={step.id}>
    <article>
      <h4>{step.title}</h4><p>{step.description}</p>
      {!!step.assumptions.length && <div className="assumptions"><strong>Допущения</strong><TextList items={step.assumptions} /></div>}
      {step.commands.map((command, i) => <CommandBlock key={`${step.id}-${i}`} command={command} />)}
      <p className="verification"><strong>Проверка: </strong>{step.verification}</p>
      <EvidenceLinks ids={step.evidence_ids} />
    </article>
  </li>)}</ol>;
}

export function RunPlanView({ plan }: { plan: AnalysisResponse['run_plan'] }) {
  return <section aria-label="План запуска">
    <h3>План запуска</h3><p>{plan.summary}</p>
    <p className="notice">Команды ещё не выполнялись. Проверьте их перед запуском на своём компьютере.</p>
    <small><code>{'<repo>'}</code> — папка клонированного проекта; <code>.</code> — текущая папка шага.</small>
    {plan.status === 'needs_input' && <div className="notice"><strong>Нужно уточнение перед запуском</strong><TextList items={plan.questions} /></div>}
    {plan.status !== 'needs_input' && !!plan.questions.length && <TextList items={plan.questions} />}
    {!!plan.prerequisites.length && <><h4>Предварительные условия</h4><TextList items={plan.prerequisites} /></>}
    {!plan.steps.length && <p>Шаги запуска пока не предоставлены.</p>}
    <RunSteps steps={plan.steps} />
  </section>;
}
