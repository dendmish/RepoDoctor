import { useState } from 'react';
import type { AnalysisResponse } from '../api/types';
import { useDiagnosis } from '../hooks/useDiagnosis';
import { downloadReport, exportMarkdown, reportFilename } from '../lib/exportMarkdown';
import { ErrorLogForm, DiagnosisPanel } from './DiagnosisPanel';
import { ErrorBanner } from './ErrorBanner';
import { EvidencePanel, EvidenceProvider } from './EvidencePanel';
import { CoverageNotice, FactsPanel, FindingsList, SummaryCard } from './ReportSections';
import { RunPlanView } from './RunPlanView';

export function AnalysisReport({ data, initialUseAI, onReanalyze }: {
  data: AnalysisResponse; initialUseAI: boolean; onReanalyze: () => void;
}) {
  const diagnosis = useDiagnosis(data.analysis_id);
  const [downloadError, setDownloadError] = useState('');
  return <div aria-label="Результат анализа">
    <EvidenceProvider items={data.evidence} prefix={`analysis-${data.analysis_id}`} synthetic={data.source_mode === 'fixture'}>
      <SummaryCard data={data} />
      <div className="report-toolbar"><button type="button" onClick={() => {
        try {
          const latest = diagnosis.state.status === 'success' ? diagnosis.state.data : undefined;
          downloadReport(exportMarkdown(data, latest), reportFilename(data)); setDownloadError('');
        } catch { setDownloadError('Не удалось скачать отчёт. Повторите экспорт.'); }
      }}>Скачать Markdown</button><small>Текущий отчёт и полученная диагностика; исходный ввод лога не включается.</small>
      {downloadError && <p role="alert">{downloadError}</p>}</div>
      <CoverageNotice coverage={data.coverage} /><FactsPanel facts={data.facts} />
      <FindingsList findings={data.findings} /><RunPlanView plan={data.run_plan} /><EvidencePanel />
    </EvidenceProvider>
    <ErrorLogForm busy={diagnosis.state.status === 'submitting'} target={data.target} initialUseAI={initialUseAI} onSubmit={diagnosis.submit} />
    {diagnosis.state.status === 'submitting' && <section aria-label="Ожидание диагностики"><p role="status">Разбираем ошибку. Ожидание — до 60 секунд.</p><button type="button" className="secondary" onClick={diagnosis.cancel}>Прекратить ожидание диагностики</button><small>Сервер может продолжить работу.</small></section>}
    {diagnosis.state.status === 'error' && <ErrorBanner error={diagnosis.state.error} title="Не удалось разобрать ошибку" onRetry={diagnosis.retry} onReanalyze={onReanalyze} />}
    {diagnosis.state.status === 'success' && <DiagnosisPanel data={diagnosis.state.data} synthetic={data.source_mode === 'fixture'} />}
  </div>;
}
