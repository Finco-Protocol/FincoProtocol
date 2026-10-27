import { useEffect, useState } from "react";
import "../../styles/rcm-analysis.css";
import { fetchInsightsHistory } from "../insights";
import type { HistoryPayload } from "../insights";
import { CompareWorkspace } from "./CompareWorkspace";
import { RunHistoryList } from "./RunHistoryList";

/** Analysis > Run history & compare (RC-UX B2 / B3).  Read-only over the committed Run History: list, filter, sort, select up to three
 *  Runs and compare them.  The selection is local view state; it never selects a scenario, saves or runs. */
export function RunsWorkspace({ project, workbookHash }: { project: string; workbookHash: string }) {
  const [history, setHistory] = useState<HistoryPayload | null>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<string[]>([]);

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
      } else setError(result.message || result.code);
    }).catch(() => { /* effect cancelled */ });
    return () => controller.abort();
  }, [project, workbookHash]);

  if (!history) return <p className="rx-boot-loading" role="status" data-runs-loading="true">{error || "Reading the committed Run history…"}</p>;
  return (
    <div data-runs-workspace="true">
      <RunHistoryList project={project} history={history} workbookHash={workbookHash} selected={selected} onSelect={setSelected} />
      <CompareWorkspace project={project} historyIds={selected} workbookHash={workbookHash} onClear={() => setSelected([])} />
    </div>
  );
}
