import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import './styles.css';

async function start() {
  const mocked = import.meta.env.DEV && import.meta.env.VITE_ENABLE_MSW === 'true';
  if (mocked) {
    const { startMocks } = await import('./mocks/browser');
    await startMocks();
  }
  createRoot(document.getElementById('root')!).render(<StrictMode><App mocked={mocked} /></StrictMode>);
}
void start().catch(() => {
  document.getElementById('root')!.textContent = 'Не удалось запустить интерфейс. Проверьте конфигурацию разработки и обновите страницу.';
});
