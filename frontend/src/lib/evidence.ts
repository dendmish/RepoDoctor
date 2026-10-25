import type { Evidence } from '../api/types';

export function safeGithubURL(value: string | null): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && url.hostname === 'github.com' &&
      !url.username && !url.password && !url.port ? url.href : null;
  } catch { return null; }
}

export function resolveEvidence(ids: string[], registry: Evidence[]) {
  const lookup = new Map(registry.map(item => [item.id, item]));
  return [...new Set(ids)].map(id => ({ id, evidence: lookup.get(id) }));
}

export function evidenceLabel(item: Evidence): string {
  const source = item.source === 'log' ? 'Обработанный лог' : item.path ?? 'Источник';
  return item.line_start === null ? source : `${source}:${item.line_start}–${item.line_end}`;
}
