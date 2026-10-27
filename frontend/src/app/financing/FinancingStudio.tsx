import { useCallback, useEffect, useState } from "react";
import "../../styles/rcm-financing.css";
import { SheetFieldsEditor } from "../workflow/SheetFieldsEditor";
import { LoadingNote, UnavailableNote } from "../workflow/workflowShared";
import { BankabilityEditor } from "./BankabilityEditor";
import { fetchFinancingStudio } from "./financingApi";
import { CapitalStackView, OverviewView, SourcesUsesPanel } from "./FinancingViews";
import { InvestorsPanel } from "./InvestorsPanel";
import type { FinancingStudioPayload } from "./types";

type Tab = "overview" | "terms" | "bankability" | "facilities" | "sources-uses" | "investors";
const TABS: ReadonlyArray<{ id: Tab; label: string }> = [
  { id: "terms", label: "Debt terms" },
  { id: "overview", label: "Overview" },
  { id: "bankability", label: "Bankability" },
  { id: "facilities", label: "Senior facilities" },
  { id: "sources-uses", label: "Sources & uses" },
  { id: "investors", label: "Investors & sponsor" },
];

function tabFromUrl(): Tab {
  const raw = new URLSearchParams(window.location.search).get("financing");
  // "Debt terms" is the default so the existing financing editor is what opens with the section (unchanged entry behaviour)
  return TABS.some((t) => t.id === raw) ? (raw as Tab) : "terms";
}

/** Financing workspace: an overview, the scalar debt terms (existing editor), the typed bankability editor, the Two-Senior
 *  capital stack and Sources & Uses.  Everything shown is read from the canonical financing authorities; the only writes are the
 *  canonical per-field Saves of the two editors, each with its own CAS. */
export function FinancingStudio({ project, reloadKey, onSaved, legacyUrl }: {
  project: string; reloadKey: number; onSaved: () => void; legacyUrl: string;
}) {
  const [tab, setTab] = useState<Tab>(tabFromUrl);
  const [studio, setStudio] = useState<FinancingStudioPayload | null>(null);
  const [error, setError] = useState<{ code: string; message?: string } | null>(null);
  const [nonce, setNonce] = useState(0);

  const load = useCallback(async () => {
    const result = await fetchFinancingStudio(project);
    if (result.ok) { setStudio(result); setError(null); } else setError(result);
  }, [project]);
  // The studio read is heavy (the full Debt-sheet context); the default Debt terms tab and Investors use their own reads, so it is
  // fetched only when a tab that shows it is open — the section's original editor then opens with exactly its original request timing.
  const needsStudio = tab !== "terms" && tab !== "investors";
  useEffect(() => { if (needsStudio) void load(); }, [load, reloadKey, nonce, needsStudio]);

  function choose(next: Tab) {
    setTab(next);
    const url = new URL(window.location.href);
    if (next === "terms") url.searchParams.delete("financing"); else url.searchParams.set("financing", next);
    window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
  }

  return (
    <div data-financing-studio="true" data-financing-tab={tab} data-financing-freshness={studio?.freshness ?? "LOADING"}>
      <div className="rcm-tabs" role="tablist" aria-label="Financing sections">
        {TABS.map((t) => (
          <button key={t.id} type="button" role="tab" id={`rcm-fin-tab-${t.id}`} aria-selected={tab === t.id} aria-controls="rcm-fin-panel"
                  className={`rcm-tab${tab === t.id ? " active" : ""}`} data-financing-tab-button={t.id} onClick={() => choose(t.id)}
                  onKeyDown={(e) => {
                    const i = TABS.findIndex((x) => x.id === tab);
                    if (e.key === "ArrowRight") { e.preventDefault(); choose(TABS[(i + 1) % TABS.length].id); }
                    if (e.key === "ArrowLeft") { e.preventDefault(); choose(TABS[(i + TABS.length - 1) % TABS.length].id); }
                  }}>{t.label}</button>
        ))}
      </div>
      <div id="rcm-fin-panel" role="tabpanel" aria-labelledby={`rcm-fin-tab-${tab}`}>
        {/* Debt terms never waits for the studio read: it is the section's original editor and opens immediately */}
        {tab === "terms" && <SheetFieldsEditor project={project} sheet="debt" title="Debt & Equity financing" reloadKey={reloadKey} onSaved={onSaved} />}
        {tab !== "terms" && !studio && (error
          ? <UnavailableNote message={error.message || "The financing view is unavailable. The classic workbook remains authoritative."} onRetry={() => setNonce((n) => n + 1)} />
          : <LoadingNote label="Loading the financing view…" />)}
        {studio && tab === "overview" && <OverviewView studio={studio} />}
        {studio && tab === "bankability" && (
          <BankabilityEditor project={project} view={studio.bankability} editable={studio.editable} identityHash={studio.identity.content_hash}
                             onSaved={() => { onSaved(); setNonce((n) => n + 1); }} onChanged={() => setNonce((n) => n + 1)} />
        )}
        {studio && tab === "facilities" && <CapitalStackView studio={studio} legacyUrl={legacyUrl} />}
        {studio && tab === "sources-uses" && <SourcesUsesPanel studio={studio} />}
        {tab === "investors" && <InvestorsPanel project={project} reloadKey={reloadKey} onSaved={() => { onSaved(); setNonce((n) => n + 1); }} />}
      </div>
    </div>
  );
}
