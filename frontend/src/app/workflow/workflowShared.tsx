// WF-React-2 — shared building blocks for the editable workflows: dirty-state
// registry, accessible dialogs, status notes and a canonical read hook.

import {
  createContext, useCallback, useContext, useEffect, useId, useMemo, useRef, useState,
  type ReactNode,
} from "react";
import "../../styles/wf-react-2.css";

export type Tone = "ok" | "error" | "conflict";
export interface StatusMessage { tone: Tone; text: string }

export function StatusNote({ status }: { status: StatusMessage | null }) {
  if (!status) return null;
  return (
    <div className="fm-info-note wf-status" role={status.tone === "ok" ? "status" : "alert"}
         data-tone={status.tone} data-wf-status={status.tone}>
      {status.text}
    </div>
  );
}

// ───────────────────────────── dirty-state registry ─────────────────────────────

interface DirtyContextValue {
  register: (key: string, count: number) => void;
  total: number;
  breakdown: Record<string, number>;
}

const DirtyContext = createContext<DirtyContextValue>({ register: () => undefined, total: 0, breakdown: {} });

/** Collects the number of unsaved edits reported by each editor so the workspace
 *  can show one honest indicator, warn before leaving and keep Run separate. */
export function DirtyProvider({ children }: { children: ReactNode }) {
  const [counts, setCounts] = useState<Record<string, number>>({});
  const register = useCallback((key: string, count: number) => {
    setCounts((prev) => {
      if ((prev[key] ?? 0) === count) return prev;
      const next = { ...prev };
      if (count > 0) next[key] = count; else delete next[key];
      return next;
    });
  }, []);
  const total = useMemo(() => Object.values(counts).reduce((sum, n) => sum + n, 0), [counts]);
  useEffect(() => {
    if (total === 0) return undefined;
    const guard = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [total]);
  const value = useMemo(() => ({ register, total, breakdown: counts }), [register, total, counts]);
  return <DirtyContext.Provider value={value}>{children}</DirtyContext.Provider>;
}

export const useDirtyTotal = () => useContext(DirtyContext);

/** Report this editor's unsaved-edit count; cleared on unmount. */
export function useReportDirty(key: string, count: number) {
  const { register } = useContext(DirtyContext);
  useEffect(() => { register(key, count); }, [register, key, count]);
  useEffect(() => () => register(key, 0), [register, key]);
}

// ───────────────────────────── canonical read hook ─────────────────────────────

type Failure = { ok: false; code: string; message?: string };
export type ReadState<T> = { state: "loading" } | { state: "error"; message: string } | { state: "ready"; data: T };

/** Canonical read with stale-while-revalidate.  `scope` identifies WHAT is read
 *  (project, sheet, scenario): changing it starts from the loading state.
 *  `refresh` and `reload()` re-read the same scope while keeping the current data
 *  on screen, so editors and their status messages are never unmounted by a
 *  successful save. */
export function useCanonicalRead<T>(
  fetcher: () => Promise<T | Failure>,
  scope: unknown[],
  refresh: unknown[] = [],
): ReadState<T> & { reload: () => void } {
  const [state, setState] = useState<ReadState<T>>({ state: "loading" });
  const [nonce, setNonce] = useState(0);
  const lastScope = useRef("");
  useEffect(() => {
    let live = true;
    const key = JSON.stringify(scope);
    const sameScope = lastScope.current === key;
    lastScope.current = key;
    setState((prev) => (sameScope && prev.state === "ready" ? prev : { state: "loading" }));
    fetcher().then((result) => {
      if (!live) return;
      if (!result || (result as { ok?: unknown }).ok !== true) {
        const failure = result as Failure;
        setState({ state: "error", message: failure?.message || failure?.code || "The server refused this read." });
      } else {
        setState({ state: "ready", data: result as T });
      }
    });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...scope, ...refresh, nonce]);
  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return Object.assign(state, { reload }) as ReadState<T> & { reload: () => void };
}

export function UnavailableNote({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="fm-banner" role="alert">
      <span className="fm-demo-label">UNAVAILABLE</span>
      <span className="fm-banner-copy">{message}</span>
      {onRetry && <button type="button" className="fm-btn" onClick={onRetry}>Retry</button>}
    </div>
  );
}

export function LoadingNote({ label = "Loading canonical data…" }: { label?: string }) {
  return <p className="fm-info-note" role="status">{label}</p>;
}

// ───────────────────────────── accessible dialog ─────────────────────────────

interface DialogProps {
  title: string;
  description?: string;
  confirmLabel: string;
  cancelLabel?: string;
  danger?: boolean;
  /** When set, the dialog collects one text value (rename). */
  input?: { label: string; initial: string };
  busy?: boolean;
  onConfirm: (value: string) => void;
  onCancel: () => void;
}

/** Modal dialog: labelled, focus moves in, Escape cancels, Tab is trapped and
 *  focus returns to the control that opened it. */
export function WorkflowDialog(props: DialogProps) {
  const { title, description, confirmLabel, cancelLabel = "Cancel", danger, input, busy, onConfirm, onCancel } = props;
  const titleId = useId();
  const descId = useId();
  const [value, setValue] = useState(input?.initial ?? "");
  const rootRef = useRef<HTMLDivElement>(null);
  const opener = useRef<HTMLElement | null>(null);

  useEffect(() => {
    opener.current = document.activeElement as HTMLElement | null;
    const first = rootRef.current?.querySelector<HTMLElement>("input, button");
    first?.focus();
    return () => opener.current?.focus?.();
  }, []);

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "Escape") { event.stopPropagation(); onCancel(); return; }
    if (event.key !== "Tab") return;
    const focusable = Array.from(rootRef.current?.querySelectorAll<HTMLElement>("input, button:not(:disabled)") ?? []);
    if (!focusable.length) return;
    const first = focusable[0], last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  };

  const trimmed = value.trim();
  const confirmDisabled = busy || (input !== undefined && (trimmed === "" || trimmed === input.initial));
  return (
    <div className="wf-dialog-backdrop" onKeyDown={onKeyDown}>
      <div ref={rootRef} className="wf-dialog" role="dialog" aria-modal="true"
           aria-labelledby={titleId} aria-describedby={description ? descId : undefined} data-wf-dialog="true">
        <h3 id={titleId}>{title}</h3>
        {description && <p id={descId} className="fm-info-note">{description}</p>}
        {input && (
          <label className="fm-field">
            <span className="fm-field-label">{input.label}</span>
            <input className="fm-input" value={value} maxLength={200} onChange={(e) => setValue(e.target.value)}
                   onKeyDown={(e) => { if (e.key === "Enter" && !confirmDisabled) { e.preventDefault(); onConfirm(trimmed); } }} />
          </label>
        )}
        <div className="fm-toolbar wf-dialog-actions">
          <button type="button" className="fm-btn" onClick={onCancel} disabled={busy}>{cancelLabel}</button>
          <button type="button" className={`fm-btn ${danger ? "wf-btn-danger" : "fm-btn-primary"}`}
                  disabled={confirmDisabled} onClick={() => onConfirm(trimmed)}>{confirmLabel}</button>
        </div>
      </div>
    </div>
  );
}

/** Field wrapper with a visible label, unit suffix and a field-level error that
 *  is announced and linked through aria-describedby. */
export function Field({ label, unit, error, hint, children, id }: {
  label: string; unit?: string; error?: string; hint?: string; children: (props: { id: string; "aria-describedby"?: string; "aria-invalid"?: boolean }) => ReactNode; id: string;
}) {
  const errorId = `${id}-error`;
  const hintId = `${id}-hint`;
  const describedBy = [error ? errorId : "", hint ? hintId : ""].filter(Boolean).join(" ") || undefined;
  return (
    <div className="wf-field" data-invalid={error ? "true" : undefined}>
      <label className="fm-field-label" htmlFor={id}>{label}{unit && <span className="wf-unit"> ({unit})</span>}</label>
      {children({ id, "aria-describedby": describedBy, "aria-invalid": error ? true : undefined })}
      {hint && <small id={hintId} className="wf-hint">{hint}</small>}
      {error && <small id={errorId} className="wf-error" role="alert">{error}</small>}
    </div>
  );
}
