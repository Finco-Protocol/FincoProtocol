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

/** Human names for the registry keys, used in the leave-confirmation dialog. */
export function describeDirtyKey(key: string): string {
  if (key === "input-grid") return "Assumption grid";
  if (key.startsWith("sheet-project_setup")) return "Project setup";
  if (key.startsWith("sheet-tax")) return "Tax and depreciation";
  if (key.startsWith("sheet-debt")) return "Financing";
  if (key.startsWith("cost-")) return "CAPEX & OPEX";
  if (key === "revenue-ppa") return "Revenue & PPA";
  if (key.startsWith("scenario-")) return "Scenarios";
  return key;
}

interface LeaveOptions {
  /** Registry keys that do not count as unsaved or unresolved work for THIS navigation. */
  ignore?: (key: string) => boolean;
  /** Reload IS the reconciliation of an unresolved mutation: it only asks about drafts. */
  draftsOnly?: boolean;
  /** Called when the user chooses to stay (e.g. to restore a changed URL hash). */
  onStay?: () => void;
}

interface DirtyContextValue {
  register: (key: string, count: number) => void;
  /** Unsaved edit count (staged but not saved). */
  total: number;
  breakdown: Record<string, number>;
  /** A mutation is in flight or its outcome is unresolved (UNKNOWN / CAS conflict). */
  registerPending: (key: string, pending: boolean) => void;
  /** Keys with a mutation in flight OR an unresolved outcome (union). */
  pendingKeys: string[];
  /** Sticky locks of UNKNOWN / conflicting outcomes: they survive an editor unmounting. */
  isUnresolved: (key: string) => boolean;
  setUnresolved: (key: string, unresolved: boolean) => void;
  /** Run `proceed` now when nothing relevant is unsaved, otherwise ask the user. */
  confirmIfDirty: (proceed: () => void, options?: LeaveOptions) => void;
}

const DirtyContext = createContext<DirtyContextValue>({
  register: () => undefined, total: 0, breakdown: {},
  registerPending: () => undefined, pendingKeys: [],
  isUnresolved: () => false, setUnresolved: () => undefined,
  confirmIfDirty: (proceed) => proceed(),
});

interface PendingLeave { proceed: () => void; onStay?: () => void; keys: string[]; count: number; unresolved: string[] }

/** Collects the unsaved edits and the unresolved mutations reported by every
 *  editor so the workspace shows one honest indicator, keeps Run separate and can
 *  ask before anything discards a draft.  Nothing here saves, runs or retries. */
export function DirtyProvider({ children }: { children: ReactNode }) {
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [pending, setPending] = useState<Record<string, true>>({});
  const countsRef = useRef<Record<string, number>>({});
  const [leave, setLeave] = useState<PendingLeave | null>(null);
  const unresolvedRef = useRef<Set<string>>(new Set());
  const inFlightRef = useRef<Set<string>>(new Set());
  const [unresolved, setUnresolvedState] = useState<string[]>([]);
  const register = useCallback((key: string, count: number) => {
    setCounts((prev) => {
      if ((prev[key] ?? 0) === count) return prev;
      const next = { ...prev };
      if (count > 0) next[key] = count; else delete next[key];
      countsRef.current = next;
      return next;
    });
  }, []);
  const setUnresolved = useCallback((key: string, value: boolean) => {
    if (value) unresolvedRef.current.add(key); else unresolvedRef.current.delete(key);
    setUnresolvedState(Array.from(unresolvedRef.current));
  }, []);
  const isUnresolved = useCallback((key: string) => unresolvedRef.current.has(key), []);
  const registerPending = useCallback((key: string, isPending: boolean) => {
    if (isPending) inFlightRef.current.add(key); else inFlightRef.current.delete(key);
    setPending((prev) => {
      if (Boolean(prev[key]) === isPending) return prev;
      const next = { ...prev };
      if (isPending) next[key] = true; else delete next[key];
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

  const confirmIfDirty = useCallback((proceed: () => void, options: LeaveOptions = {}) => {
    const keys = Object.keys(countsRef.current).filter((k) => !(options.ignore?.(k)));
    const count = keys.reduce((sum, k) => sum + (countsRef.current[k] ?? 0), 0);
    // A mutation in flight or with an unknown outcome must not be walked away from silently
    // either, even when its editor holds no staged draft (deactivate, scenario action, Run).
    // (`inFlightRef` holds the keys of MOUNTED editors that are pending or locked; an unresolved lock of an
    // editor that is no longer on screen stays sticky for its remount but is not asked about again.)
    const open = options.draftsOnly ? [] : Array.from(inFlightRef.current).filter((k) => !(options.ignore?.(k)));
    if (count === 0 && open.length === 0) { proceed(); return; }
    setLeave({ proceed, onStay: options.onStay, keys, count, unresolved: open });
  }, []);

  const pendingKeys = useMemo(() => Array.from(new Set([...Object.keys(pending), ...unresolved])), [pending, unresolved]);
  const value = useMemo(
    () => ({ register, total, breakdown: counts, registerPending, pendingKeys, isUnresolved, setUnresolved, confirmIfDirty }),
    [register, total, counts, registerPending, pendingKeys, isUnresolved, setUnresolved, confirmIfDirty],
  );
  return (
    <DirtyContext.Provider value={value}>
      {children}
      {leave && (
        <WorkflowDialog
          title={leave.count > 0 ? "Discard unsaved changes?" : "Leave while a change is unresolved?"}
          description={[
            leave.count > 0
              ? `You have ${leave.count} unsaved edit${leave.count === 1 ? "" : "s"} in ${Array.from(new Set(leave.keys.map(describeDirtyKey))).join(", ")}. `
                + "Nothing has been saved and the model has not been run. Staying keeps your changes exactly as they are."
              : "",
            leave.unresolved.length > 0
              ? `A save or change in ${Array.from(new Set(leave.unresolved.map(describeDirtyKey))).join(", ")} is still in progress or its outcome is unknown. `
                + "Leaving does not cancel or retry it; those editors stay locked until you reload the workspace to reconcile."
              : "",
          ].filter(Boolean).join(" ")}
          confirmLabel={leave.count > 0 ? "Discard changes and continue" : "Leave anyway"} cancelLabel="Stay and keep editing" danger
          onCancel={() => { const l = leave; setLeave(null); l.onStay?.(); }}
          onConfirm={() => { const l = leave; setLeave(null); l.proceed(); }} />
      )}
    </DirtyContext.Provider>
  );
}

export const useDirtyTotal = () => useContext(DirtyContext);
export const useLeaveGuard = () => useContext(DirtyContext).confirmIfDirty;

/** Report this editor's unsaved-edit count; cleared on unmount. */
export function useReportDirty(key: string, count: number) {
  const { register } = useContext(DirtyContext);
  useEffect(() => { register(key, count); }, [register, key, count]);
  useEffect(() => () => register(key, 0), [register, key]);
}

/** Sticky lock for an UNKNOWN / conflicting outcome.  The lock lives in the provider,
 *  so it survives the editor unmounting (navigation) and a remount starts locked:
 *  only an explicit reconciliation (a reload, or `set(false)`) clears it. */
export function useUnresolvedLock(key: string): [boolean, (locked: boolean) => void] {
  const { isUnresolved, setUnresolved } = useContext(DirtyContext);
  const [locked, setLocal] = useState(() => isUnresolved(key));
  const set = useCallback((value: boolean) => { setUnresolved(key, value); setLocal(value); }, [key, setUnresolved]);
  return [locked, set];
}

/** Report that this editor has a mutation in flight or an unresolved outcome. */
export function useReportPending(key: string, pending: boolean) {
  const { registerPending } = useContext(DirtyContext);
  useEffect(() => { registerPending(key, pending); }, [registerPending, key, pending]);
  useEffect(() => () => registerPending(key, false), [registerPending, key]);
}

/** Synchronous single-flight guard: a second activation before the first
 *  finishes (double click, repeated Enter) is dropped, even within one render. */
export function useSingleFlight() {
  const active = useRef(false);
  return useCallback(async <T,>(task: () => Promise<T>): Promise<T | undefined> => {
    if (active.current) return undefined;
    active.current = true;
    try {
      return await task();
    } finally {
      active.current = false;
    }
  }, []);
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
