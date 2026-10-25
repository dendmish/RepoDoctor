import { createContext, useContext, type ReactNode } from 'react';
import type { Evidence } from '../api/types';
import { evidenceLabel, resolveEvidence, safeGithubURL } from '../lib/evidence';

type Registry = { items: Evidence[]; prefix: string; synthetic: boolean };
const EvidenceContext = createContext<Registry>({ items: [], prefix: 'evidence', synthetic: false });
const elementId = (prefix: string, id: string) => `${prefix}-${encodeURIComponent(id)}`;

export function EvidenceProvider({ children, ...registry }: Registry & { children: ReactNode }) {
  return <EvidenceContext.Provider value={registry}>{children}</EvidenceContext.Provider>;
}

export function EvidenceLinks({ ids }: { ids: string[] }) {
  const registry = useContext(EvidenceContext);
  if (!ids.length) return null;
  return <ul className="evidence-links" aria-label="Источники утверждения">
    {resolveEvidence(ids, registry.items).map(({ id, evidence }) => <li key={id}>
      {evidence ? <a href={`#${elementId(registry.prefix, id)}`} onClick={event => {
        event.preventDefault();
        const detail = document.getElementById(elementId(registry.prefix, id));
        if (detail instanceof HTMLDetailsElement) {
          detail.open = true;
          detail.focus();
        }
      }}>{evidenceLabel(evidence)}</a> : <span className="broken-reference">Источник недоступен: {id}</span>}
    </li>)}
  </ul>;
}

export function EvidencePanel() {
  const { items, prefix, synthetic } = useContext(EvidenceContext);
  return <section aria-label="Доказательства" className="evidence-panel">
    <h3>Доказательства</h3>
    {!items.length && <p className="muted">Источники не предоставлены.</p>}
    {items.map(item => {
      const url = synthetic || item.source === 'log' ? null : safeGithubURL(item.url);
      return <details id={elementId(prefix, item.id)} tabIndex={-1} key={item.id}>
        <summary>{evidenceLabel(item)} <span className="badge">{item.source}</span></summary>
        <pre className="excerpt">{item.excerpt}</pre>
        {item.source === 'log' ? <small>Строки обработанного лога; внешний адрес отсутствует.</small>
          : synthetic ? <small>Синтетический локальный пример.</small>
            : url ? <a href={url} target="_blank" rel="noopener noreferrer">Открыть источник в GitHub</a>
              : <small>Внешняя ссылка отсутствует или не разрешена.</small>}
      </details>;
    })}
  </section>;
}
