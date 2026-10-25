import { ApiError } from '../api/client';

const guidance: Record<string, string> = {
  INVALID_INPUT: 'Проверьте поля формы и исправьте указанные данные.',
  REPOSITORY_NOT_FOUND: 'Проверьте URL и публичную доступность репозитория.',
  REF_NOT_FOUND: 'Проверьте название ветки, тега или commit.',
  EMPTY_REPOSITORY: 'В репозитории ещё нет доступного commit для анализа.',
  UNSUPPORTED_REPOSITORY: 'Используйте поддерживаемый публичный GitHub-репозиторий.',
  PAYLOAD_TOO_LARGE: 'Сократите ввод и отправьте нужный фрагмент ошибки.',
  ANALYSIS_NOT_FOUND: 'Контекст анализа истёк, был вытеснен или потерян при перезапуске сервера. Повторите анализ репозитория.',
  GITHUB_RATE_LIMITED: 'GitHub ограничил запросы. Подождите и повторите вручную.',
  SERVER_BUSY: 'Все слоты сервера заняты. Повторите вручную позже.',
  GITHUB_UNAVAILABLE: 'GitHub временно недоступен. Повторите вручную позже.',
  ANALYSIS_TIMEOUT: 'Сервер не успел завершить операцию. Повторите вручную.',
  CLIENT_TIMEOUT: 'Время ожидания истекло. Сервер мог продолжить работу; повтор не запускается автоматически.',
  ABORTED: 'Вы прекратили ожидание. Сервер мог продолжить работу.',
  NETWORK_ERROR: 'Проверьте соединение с сервером и повторите вручную.',
  INVALID_RESPONSE: 'Получен некорректный ответ сервера. Повторите позже.',
  INTERNAL_ERROR: 'Внутренняя ошибка сервера. Сохраните Request ID для диагностики.',
};

export function ErrorBanner({ error, title, onRetry, onReanalyze }: {
  error: ApiError; title: string; onRetry?: () => void; onReanalyze?: () => void;
}) {
  const expired = error.code === 'ANALYSIS_NOT_FOUND';
  return <section role="alert" className="error-banner">
    <h3>{title}</h3><p>{error.message}</p>
    <p>{guidance[error.code] ?? 'Проверьте данные запроса. При повторении ошибки сохраните Request ID.'}</p>
    <p>Код: {error.code}</p>{error.requestId && <p>Request ID: {error.requestId}</p>}
    {!!error.details.length && <ul>{error.details.map((detail, i) => <li key={i}>{detail}</li>)}</ul>}
    {expired && onReanalyze ? <button type="button" onClick={onReanalyze}>Повторить анализ репозитория</button>
      : error.retryable && onRetry ? <button type="button" onClick={onRetry}>Повторить запрос</button>
        : !expired && <small>Проверьте введённые данные перед новой отправкой.</small>}
  </section>;
}
