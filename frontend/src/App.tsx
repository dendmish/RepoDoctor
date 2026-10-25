import { AnalysisForm } from './components/AnalysisForm';
import { useAnalysis } from './hooks/useAnalysis';

export default function App({ mocked = false }: { mocked?: boolean }) {
  const { state, submit, cancel } = useAnalysis();
  return (
    <main>
      <header>
        <p className="eyebrow">REPO DOCTOR</p>
        <h1>Разберитесь, как запустить проект</h1>
        <p>Укажите репозиторий и своё окружение, чтобы начать анализ.</p>
      </header>
      {mocked && (
        <aside className="notice">
          Демонстрация MSW: ответы — синтетические примеры контракта, без обращения к backend.
        </aside>
      )}
      <AnalysisForm busy={state.status === 'submitting'} onSubmit={submit} />
      {state.status === 'submitting' && (
        <section aria-label="Ожидание анализа">
          <p role="status">
            <span className="spinner" aria-hidden="true" />
            Ожидаем ответ. Анализ может занять до 100 секунд.
          </p>
          <button className="secondary" onClick={cancel}>Прекратить ожидание</button>
          <small>Сервер может продолжить работу после прекращения ожидания.</small>
        </section>
      )}
      {state.status === 'error' && (
        <section role="alert">
          <h2>Не удалось завершить анализ</h2>
          <p>{state.error.message}</p>
          <p>Код: {state.error.code}</p>
          {state.error.requestId && <p>Request ID: {state.error.requestId}</p>}
          {state.error.details.map((detail, i) => <p key={i}>{detail}</p>)}
          <p>{state.error.retryable
            ? 'Нажмите «Анализировать», чтобы повторить вручную.'
            : 'Проверьте введённые данные перед новой отправкой.'}</p>
        </section>
      )}
      {state.status === 'success' && (
        <section aria-label="Результат анализа">
          <h2>{state.data.repository.name}</h2>
          <p role="status">Ответ получен</p>
          <p>Источник: {state.data.source_mode} · Генерация: {state.data.generation.mode}</p>
          {state.data.generation.reason && <p>Причина: {state.data.generation.reason}</p>}
          <p>{state.data.target.os} / {state.data.target.shell}</p>
          <p>{state.data.run_plan.summary}</p>
          {state.data.warnings.map((warning, i) => <p key={i}>{warning}</p>)}
          <small>
            Каркас D1. Полный отчёт и диагностика появятся в следующих этапах.
            Команды не выполнялись.
          </small>
        </section>
      )}
    </main>
  );
}
