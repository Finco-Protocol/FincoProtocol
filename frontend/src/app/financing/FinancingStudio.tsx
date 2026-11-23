import { useCallback, useEffect, useState } from "react";
import "../../styles/rcm-financing.css";
import { SheetFieldsEditor } from "../workflow/SheetFieldsEditor";
import { LoadingNote, UnavailableNote, useLeaveGuard, useDirtyTotal, WorkflowDialog } from "../workflow/workflowShared";
import { BankabilityEditor } from "./BankabilityEditor";
import { fetchFinancingStudio } from "./financingApi";
import { CapitalStackView, OverviewView, SourcesUsesPanel } from "./FinancingViews";
import { InvestorsPanel } from "./InvestorsPanel";
import { DebtMetricsWorkspace } from "../debtmetrics/DebtMetricsWorkspace";
import { selectedRunFromUrl } from "../debtmetrics/debtMetricsLink";
import { FinancingReadLayer } from "./pr3b1/FinancingReadLayer";
import type { FinancingStudioPayload } from "./types";

type Tab = "workspace" | "overview" | "terms" | "bankability" | "facilities" | "sources-uses" | "investors" | "debt-metrics";
const TABS: ReadonlyArray<{ id: Tab; label: string }> = [
  { id: "terms", label: "Debt terms" },
  { id: "overview", label: "Overview" },
  { id: "debt-metrics", label: "Debt metrics" },
  { id: "bankability", label: "Bankability" },
  { id: "facilities", label: "Senior facilities" },
  { id: "sources-uses", label: "Sources & uses" },
  { id: "investors", label: "Investors & sponsor" },
];

function tabFromUrl(): Tab {
  const raw = new URLSearchParams(window.location.search).get("financing");
  // Missing/unknown legacy selector opens the single Financing workspace. Explicit selectors preserve every existing editor.
  return TABS.some((t) => t.id === raw) ? (raw as Tab) : "workspace";
}

/** Financing workspace: an overview, the scalar debt terms (existing editor), the typed bankability editor, the Two-Senior
 *  capital stack and Sources & Uses.  Everything shown is read from the canonical financing authorities; the only writes are the
 *  canonical per-field Saves of the two editors, each with its own CAS. */
export function FinancingStudio({ project, scenarioId, reloadKey, onSaved }: {
  project: string; scenarioId: string | null; reloadKey: number; onSaved: () => void;
}) {
  const [tab, setTab] = useState<Tab>(tabFromUrl);
  const [studio, setStudio] = useState<FinancingStudioPayload | null>(null);
  const [error, setError] = useState<{ code: string; message?: string } | null>(null);
  const [nonce, setNonce] = useState(0);
  const guard = useLeaveGuard();
  const { pendingKeys, breakdown, isUnresolved } = useDirtyTotal();
  const [leaveDocument, setLeaveDocument] = useState<Tab | null>(null);
  const [navigationNotice, setNavigationNotice] = useState<string | null>(null);
  useEffect(() => { setLeaveDocument(null); setNavigationNotice(null); }, [project, scenarioId]);

  const load = useCallback(async () => {
    const result = await fetchFinancingStudio(project);
    if (result.ok) { setStudio(result); setError(null); } else setError(result);
  }, [project]);
  // The studio read is heavy (the full Debt-sheet context); the default Debt terms tab and Investors use their own reads, so it is
  // fetched only when a tab that shows it is open — the section's original editor then opens with exactly its original request timing.
  const needsStudio = tab !== "workspace" && tab !== "terms" && tab !== "investors" && tab !== "debt-metrics";
  useEffect(() => { if (needsStudio) void load(); }, [load, reloadKey, nonce, needsStudio]);

  function adopt(next: Tab) {
    setTab(next);
    const url = new URL(window.location.href);
    url.hash = "financing";
    if (next === "workspace") url.searchParams.delete("financing"); else url.searchParams.set("financing", next);
    window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
  }
  function choose(next: Tab) {
    if (next === tab) return;
    // Internal document navigation discards only the mounted local document.
    // Shared scalar drafts remain in ChangesProvider; global shell navigation
    // retains its existing guard and discard semantics.
    const documentKey = tab === 'investors' ? 'sheet-debt-investors'
      : tab === 'workspace' || tab === 'bankability' ? 'sheet-debt-bankability' : null;
    const relevant = (key: string) => key === documentKey || key === 'sheet-debt' || key === 'sheet-debt-inline';
    if (pendingKeys.some(key => relevant(key) && !isUnresolved(key))) {
      setNavigationNotice('A Financing Save is in progress. Wait for its result before changing views.');
      return;
    }
    setNavigationNotice(null);
    if (documentKey && ((breakdown[documentKey] ?? 0) > 0 || pendingKeys.includes(documentKey))) {
      setLeaveDocument(next);
      return;
    }
    guard(() => adopt(next), { ignore: key => !['sheet-debt', 'sheet-debt-inline'].includes(key) || !pendingKeys.includes(key) });
  }

  return (
    <div data-financing-studio="true" data-financing-tab={tab} data-financing-freshness={studio?.freshness ?? "LOADING"}>
      {navigationNotice && <p role="status">{navigationNotice}</p>}
      {leaveDocument && <WorkflowDialog title="Leave this Financing document?"
        description="Unsaved edits in this document will be discarded. Separate scalar drafts are retained. Leaving does not cancel or retry an unresolved Save; reload the workspace to reconcile its outcome."
        confirmLabel="Discard document and continue" cancelLabel="Stay and keep editing" danger
        onCancel={() => setLeaveDocument(null)} onConfirm={() => { const next = leaveDocument; setLeaveDocument(null); adopt(next); }} />}
      {/* UX-FINAL-01: ONE always-visible Financing navigation (workspace + the seven existing views) in every view, replacing the "Back" paragraph and the collapsed
          disclosure. Contracts kept: aria-label "Existing Financing functions" lists exactly the seven views via data-financing-tab-button, and the sub-view
          button still reads "Back to Financing workspace". In the workspace the in-page read links own data-financing-tab-button, so the nav uses data-financing-nav there. */}
      <nav className="pr3b1-compat ux-fin-nav" aria-label="Existing Financing functions">
        <button type="button" className="rx-button rx-button-secondary" aria-current={tab === "workspace" ? "page" : undefined} data-financing-workspace-button="true"
          onClick={() => choose("workspace")}>{tab === "workspace" ? "Financing workspace" : "Back to Financing workspace"}</button>
        {TABS.map(t => <button key={t.id} type="button" className="rx-button rx-button-secondary" aria-current={tab === t.id ? 'page' : undefined}
          {...(tab === "workspace" ? { "data-financing-nav": t.id } : { "data-financing-tab-button": t.id })} onClick={() => choose(t.id)}>{t.label}</button>)}
      </nav>
      {tab === "workspace" ? <FinancingReadLayer scope={{ project, scenarioId, historyId: selectedRunFromUrl() ?? undefined }} reloadKey={reloadKey} onSaved={onSaved} onOpenExisting={view => { if (TABS.some(t => t.id === view)) choose(view as Tab); }} /> : <>
      <div id="rcm-fin-panel">
        {/* Debt terms never waits for the studio read: it is the section's original editor and opens immediately */}
        {tab === "terms" && <SheetFieldsEditor project={project} sheet="debt" title="Debt & Equity financing" reloadKey={reloadKey} onSaved={onSaved} />}
        {tab !== "terms" && tab !== "debt-metrics" && tab !== "investors" && !studio && (error
          ? <UnavailableNote message={error.message || "The financing view is unavailable right now. Nothing was changed."} onRetry={() => setNonce((n) => n + 1)} />
          : <LoadingNote label="Loading the financing view…" />)}
        {studio && tab === "overview" && <OverviewView studio={studio} />}
        {studio && tab === "bankability" && (
          <BankabilityEditor project={project} view={studio.bankability} editable={studio.editable} identityHash={studio.identity.content_hash}
                             onSaved={() => { onSaved(); setNonce((n) => n + 1); }} onChanged={() => setNonce((n) => n + 1)} />
        )}
        {studio && tab === "facilities" && <CapitalStackView studio={studio} />}
        {studio && tab === "sources-uses" && <SourcesUsesPanel studio={studio} />}
        {tab === "debt-metrics" && <DebtMetricsWorkspace project={project} reloadKey={reloadKey} onEditTerms={() => choose("terms")} />}
        {tab === "investors" && <InvestorsPanel project={project} reloadKey={reloadKey} onSaved={() => { onSaved(); setNonce((n) => n + 1); }} />}
      </div>
      </>}
    </div>
  );
}
