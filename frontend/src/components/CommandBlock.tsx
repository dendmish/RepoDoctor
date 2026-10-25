import { useState } from 'react';
import type { Command } from '../api/types';

export async function copyCommand(text: string): Promise<void> {
  if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
  await navigator.clipboard.writeText(text);
}

export function CommandBlock({ command }: { command: Command }) {
  const [feedback, setFeedback] = useState('');
  const [copying, setCopying] = useState(false);
  return <div className="command-block">
    <div className="command-meta"><span>Shell: <strong>{command.shell}</strong></span><span>Папка: <code>{command.cwd}</code></span></div>
    <pre><code>{command.text}</code></pre>
    {command.explanation && <p>{command.explanation}</p>}
    {command.requires_review && <small>Проверьте команду перед выполнением.</small>}
    <button type="button" className="secondary compact" disabled={copying} onClick={async () => {
      setCopying(true);
      try { await copyCommand(command.text); setFeedback('Команда скопирована.'); }
      catch { setFeedback('Не удалось скопировать. Выделите команду и скопируйте вручную.'); }
      finally { setCopying(false); }
    }}>Скопировать команду</button>
    {feedback && <span className="copy-feedback" role="status">{feedback}</span>}
  </div>;
}
