import { useState, type FormEvent } from 'react';
import type { AnalysisRequest, TargetEnvironment } from '../api/types';

const shells = { windows: 'powershell', linux: 'bash', macos: 'zsh' } as const satisfies Record<TargetEnvironment['os'], TargetEnvironment['shell']>;
export function AnalysisForm({ busy, onSubmit }: { busy: boolean; onSubmit: (request: AnalysisRequest) => void }) {
  const [os, setOS] = useState<TargetEnvironment['os']>('windows');
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const data = new FormData(event.currentTarget);
    onSubmit({ repo_url: String(data.get('repo_url')).trim(), ref: String(data.get('ref')).trim() || null,
      target: { os, shell: shells[os] }, use_ai: data.get('use_ai') === 'on' });
  }
  return <form onSubmit={submit} aria-label="Анализ репозитория">
    <fieldset disabled={busy}>
      <legend>Репозиторий и окружение</legend>
      <label htmlFor="repo_url">URL публичного GitHub-репозитория</label>
      <input id="repo_url" name="repo_url" type="url" required maxLength={2048} placeholder="https://github.com/owner/repo" aria-describedby="url-help" />
      <small id="url-help">Укажите owner/repo. Ветку, тег или commit задайте отдельно.</small>
      <label htmlFor="ref">Ветка, тег или commit (необязательно)</label>
      <input id="ref" name="ref" maxLength={200} placeholder="Ветка по умолчанию" />
      <div className="target-fields"><div><label htmlFor="os">Операционная система</label>
        <select id="os" value={os} onChange={event => setOS(event.target.value as TargetEnvironment['os'])}>
          <option value="windows">Windows</option><option value="linux">Linux</option><option value="macos">macOS</option>
        </select></div><div><label htmlFor="shell">Shell</label>
        <select id="shell" value={shells[os]} disabled><option value={shells[os]}>{shells[os]}</option></select>
      </div></div>
      <label className="checkbox"><input type="checkbox" name="use_ai" defaultChecked /> Использовать AI</label>
      <small>При включении AI фрагменты файлов репозитория будут отправлены внешней модели для подготовки плана.</small>
      <button type="submit" disabled={busy}>{busy ? 'Анализируем…' : 'Анализировать'}</button>
    </fieldset>
  </form>;
}
