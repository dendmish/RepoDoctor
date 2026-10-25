import { AnalysisForm } from './components/AnalysisForm';
import { AnalysisReport } from './components/AnalysisReport';
import { ErrorBanner } from './components/ErrorBanner';
import { useAnalysis } from './hooks/useAnalysis';

export default function App({ mocked = false }: { mocked?: boolean }) {
  const { state, submit, cancel, retry, lastRequest } = useAnalysis();
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
      {state.status === 'error' && <ErrorBanner error={state.error} title="Не удалось завершить анализ" onRetry={retry} />}
      {state.status === 'success' && (
        <AnalysisReport key={state.data.analysis_id} data={state.data} initialUseAI={lastRequest?.use_ai ?? true} onReanalyze={retry} />
      )}
    </main>
  );
}
