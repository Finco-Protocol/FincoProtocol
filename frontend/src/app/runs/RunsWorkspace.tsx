import { useEffect, useState } from "react";
import "../../styles/rcm-analysis.css";
import { fetchInsightsHistory } from "../insights";
import type { HistoryPayload } from "../insights";
import { CreditDecisionPanel } from "../credit/CreditDecisionPanel";
import { CompareWorkspace } from "./CompareWorkspace";
import { HistoricalStatements } from "./HistoricalStatements";
import { RunHistoryList } from "./RunHistoryList";
import { friendlyMessage } from "../productLanguage";

/** Analysis > Run history & compare (RC-UX B2 / B3).  Read-only over the committed Run History: list, filter, sort, select up to three
 *  Runs and compare them.  The selection is local view state; it never selects a scenario, saves or runs. */
export function RunsWorkspace({ project, workbookHash }: { project: string; workbookHash: string }) {
  const [history, setHistory] = useState<HistoryPayload | null>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  // The earlier Run whose saved statements are open; kept in the URL (`?statements=`) so it can be linked, refreshed and left with Back.
  const [statementsFor, setStatementsFor] = useState(() => new URLSearchParams(window.location.search).get("statements") ?? "");
  function openStatements(historyId: string) {
    setStatementsFor(historyId);
    const url = new URL(window.location.href);
    if (historyId) url.searchParams.set("statements", historyId); else url.searchParams.delete("statements");
    window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
  }

  // Re-read after a Save or Run (the Working Copy hash changes) so CURRENT / STALE / MATCHES labels follow the canonical state.
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    void fetchInsightsHistory(project, controller.signal).then((result) => {
      if (controller.signal.aborted) return;
      if (result.ok) {
        setHistory(result);
        const known = new Set(result.history.map((r) => r.identity.history_id));
        setSelected((current) => current.filter((id) => known.has(id)));
      } else setError(friendlyMessage(result.code, result.message));
    }).catch(() => { /* effect cancelled */ });
    return () => controller.abort();
  }, [project, workbookHash]);

  if (!history) return <p className="rx-boot-loading" role="status" data-runs-loading="true">{error || "Reading the committed Run history…"}</p>;
  if (statementsFor) return <div data-runs-workspace="true"><HistoricalStatements project={project} historyId={statementsFor} onBack={() => openStatements("")} /></div>;
  return (
    <div data-runs-workspace="true">
      <RunHistoryList project={project} history={history} workbookHash={workbookHash} selected={selected} onSelect={setSelected} onOpenStatements={openStatements} />
      <CompareWorkspace project={project} historyIds={selected} workbookHash={workbookHash} onClear={() => setSelected([])} />
      <CreditDecisionPanel project={project} historyIds={selected} workbookHash={workbookHash} />
    </div>
  );
}
