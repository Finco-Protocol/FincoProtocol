import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { encodeSpec, fetchCapexPreview, fetchCapexProfiles, saveCapexProfile } from "./api";
import type { CapexPlan, CapexProfiles, SavedRow } from "./types";
import { emptyProfileRow, profileDraftFromSaved, profileDocument, rowProblems, sameDraftRow, sameProfileDocument,
  wireProfileDraft, type ProfileDraft, type ProfileDraftRow } from "./profileDraft";
import { isUserLineKey } from "./profileFocus";
import { useDirtyTotal, useRegisterDiscard, useReportDirty, useReportPending, useSingleFlight, useUnresolvedLock } from "../workflow/workflowShared";

interface WorkspaceSignal { project: string; scenario: string; hash: string; version: number; onSaved: () => void }
interface State {
  data: CapexProfiles | null; baseline: CapexProfiles | null; draft: ProfileDraft; history: ProfileDraft[]; future: ProfileDraft[];
  plan: { plan: CapexPlan; spec: string; project: string; scenario: string; hash: string } | null;
  busy: "" | "preview" | "save"; loadError: string; stale: string;
  status: { tone: "ok" | "error" | "conflict"; text: string } | null;
  error: { code: string; message: string } | null; dialog: "reset" | "orphans" | null;
}
const initial = (): State => ({ data: null, baseline: null, draft: {}, history: [], future: [], plan: null, busy: "", loadError: "", stale: "", status: null, error: null, dialog: null });
const scopeOf = (data: CapexProfiles) => `${data.project.code}|${data.save.scenario_id}`;
interface Submission { project: string; scope: string; expected: Record<string, SavedRow> }

function useController(project: string, reloadKey = 0, onSaved?: () => void) {
  const [state, setState] = useState<State>(initial);
  const current = useRef(state);
  const projectRef = useRef(project); projectRef.current = project;
  const signal = useRef<WorkspaceSignal | null>(null);
  const active = useRef(false);
  const mountedProject = useRef(project);
  const generation = useRef(0);
  const previewTicket = useRef(0);
  const readAbort = useRef<AbortController | null>(null);
  const previewAbort = useRef<AbortController | null>(null);
  const submitted = useRef<Submission | null>(null);
  const callback = useRef(onSaved); callback.current = onSaved;
  const [locked, setLocked] = useUnresolvedLock("capex-profile");
  const lockedRef = useRef(locked); lockedRef.current = locked;
  const singleFlight = useSingleFlight();
  const { pendingKeys } = useDirtyTotal();
  const externalPending = pendingKeys.some(k => k !== "capex-profile" && k !== "run");
  const registerDiscard = useRegisterDiscard();
  const update = useCallback((fn: (s: State) => State) => { const next = fn(current.current); current.current = next; setState(next); }, []);
  const dirtyOf = (s: State) => {
    if (!s.baseline) return 0;
    const saved = profileDraftFromSaved(s.baseline);
    return [...new Set([...Object.keys(saved), ...Object.keys(s.draft)])]
      .filter(k => !sameDraftRow(s.draft[k] ?? emptyProfileRow(), saved[k] ?? emptyProfileRow())).length;
  };
  const load = useCallback(async () => {
    const askedProject = projectRef.current;
    const askedScenario = signal.current?.project === askedProject ? signal.current.scenario : undefined;
    const ticket = ++generation.current;
    readAbort.current?.abort();
    const abort = new AbortController(); readAbort.current = abort;
    const result = await fetchCapexProfiles(askedProject, abort.signal);
    if (ticket !== generation.current || abort.signal.aborted || askedProject !== projectRef.current) return null;
    if (!result.ok) { update(s => ({ ...s, loadError: result.message ?? result.code, stale: dirtyOf(s) ? "The saved state could not be refreshed. Draft retained; reconcile before saving." : s.stale })); return null; }
    if (result.project.code !== askedProject || (askedScenario !== undefined && result.save.scenario_id !== askedScenario)
      || result.months !== result.timeline.months) {
      update(s => ({ ...s, loadError: "The profile response belongs to a different project/scenario or duration. Reload the workspace.", stale: "Profile identity could not be verified; the draft is retained." }));
      return null;
    }
    update(s => {
      const retain = dirtyOf(s) > 0 || s.busy === "save" || lockedRef.current;
      const moved = s.baseline && (scopeOf(s.baseline) !== scopeOf(result) || s.baseline.save.content_hash !== result.save.content_hash);
      return { ...s, data: result, loadError: "", ...(retain ? { stale: moved ? "The saved project or scenario changed. Draft retained; reconcile before saving." : s.stale }
        : { baseline: result, draft: profileDraftFromSaved(result), history: [], future: [], stale: "", plan: null }) };
    });
    return result;
  }, [update]);
  const activate = useCallback(() => { if (!active.current) { active.current = true; void load(); } }, [load]);
  const syncWorkspace = useCallback((next: WorkspaceSignal) => {
    if (next.project !== projectRef.current) return;
    const old = signal.current; signal.current = next;
    if (current.current.baseline && dirtyOf(current.current) && (current.current.baseline.save.content_hash !== next.hash || scopeOf(current.current.baseline) !== `${next.project}|${next.scenario}`)) {
      update(s => ({ ...s, stale: "The saved project/scenario changed. The profile draft is retained and must be reconciled." }));
    }
    if (active.current && (!old || old.project !== next.project || old.scenario !== next.scenario || old.hash !== next.hash || old.version !== next.version)) {
      previewAbort.current?.abort(); ++previewTicket.current;
      void load();
    }
  }, [load, update]);
  useEffect(() => {
    if (mountedProject.current !== project) {
      mountedProject.current = project;
      if (signal.current?.project !== project) signal.current = null;
    ++generation.current; ++previewTicket.current;
    readAbort.current?.abort(); previewAbort.current?.abort();
    }
    if (active.current) void load();
    return () => { ++generation.current; ++previewTicket.current; readAbort.current?.abort(); previewAbort.current?.abort(); };
  }, [project, load]);
  useEffect(() => { if (active.current && reloadKey) void load(); }, [reloadKey, load]);

  const expectedScenario = signal.current?.project === project ? signal.current.scenario : undefined;
  const data = state.data?.project.code === project && (expectedScenario === undefined || state.data.save.scenario_id === expectedScenario) ? state.data : null;
  const scopeMismatch = Boolean(state.baseline && (state.baseline.project.code !== project || (data && scopeOf(state.baseline) !== scopeOf(data))
    || (signal.current?.project === project && state.baseline.save.scenario_id !== signal.current.scenario)));
  const dirtyCount = dirtyOf(state);
  useReportDirty("capex-profile", dirtyCount);
  useReportPending("capex-profile", state.busy !== "" || locked);
  useEffect(() => {
    if (!dirtyCount && !state.busy && !locked) return;
    const guard = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [dirtyCount, state.busy, locked]);
  const keys = data?.items.map(i => i.item_key) ?? [];
  const saved = data ? profileDraftFromSaved(data) : {};
  const readOnly = !data?.edit.allowed || scopeMismatch || locked || state.busy !== "";
  const editable = (key: string) => Boolean(data?.items.some(i => i.item_key === key) && !isUserLineKey(key) && !readOnly);
  const problems = data ? keys.flatMap(key => rowProblems(state.draft[key] ?? emptyProfileRow(), data.months, data.shapes).map(message => ({ key, message }))) : [];
  const orphans = data ? [...new Set([...Object.keys(data.saved.rows), ...Object.keys(state.draft).filter(k => state.draft[k]?.shape)])].filter(k => !keys.includes(k)) : [];
  const change = (key: string, patch: Partial<ProfileDraftRow>) => {
    if (!editable(key)) return;
    previewAbort.current?.abort(); ++previewTicket.current;
    update(s => ({ ...s, history: [...s.history.slice(-19), s.draft], future: [], draft: { ...s.draft, [key]: { ...(s.draft[key] ?? emptyProfileRow()), ...patch } }, status: null }));
  };
  const changeShape = (key: string, shape: string) => {
    if (shape && !data?.shapes.includes(shape)) return;
    change(key, { ...emptyProfileRow(), shape });
  };
  const undo = () => {
    if (readOnly) return;
    previewAbort.current?.abort(); ++previewTicket.current;
    update(s => s.history.length ? { ...s, draft: s.history[s.history.length - 1], history: s.history.slice(0, -1), future: [s.draft, ...s.future].slice(0, 20), status: null } : s);
  };
  const redo = () => {
    if (readOnly) return;
    previewAbort.current?.abort(); ++previewTicket.current;
    update(s => s.future.length ? { ...s, draft: s.future[0], history: [...s.history.slice(-19), s.draft], future: s.future.slice(1), status: null } : s);
  };
  const discard = useCallback(() => {
    if (current.current.busy === "save" || lockedRef.current) return;
    previewAbort.current?.abort(); ++previewTicket.current;
    update(s => {
      const fresh = s.data?.project.code === projectRef.current ? s.data : null;
      const sameBaseline = fresh && s.baseline && scopeOf(fresh) === scopeOf(s.baseline) && fresh.save.content_hash === s.baseline.save.content_hash;
      return { ...s, baseline: fresh, draft: fresh ? profileDraftFromSaved(fresh) : {}, future: [], history: sameBaseline ? [...s.history.slice(-19), s.draft] : [], stale: "", status: null, plan: null };
    });
  }, [update]);
  useEffect(() => registerDiscard(ks => { if (ks.includes("capex-profile")) discard(); }), [registerDiscard, discard]);
  const applyBulk = (shape: string) => {
    if (readOnly || !data?.shapes.includes(shape) || ["EXPLICIT", "MILESTONE"].includes(shape)) return;
    update(s => ({ ...s, history: [...s.history.slice(-19), s.draft], future: [], draft: { ...s.draft,
      ...Object.fromEntries(keys.filter(k => !isUserLineKey(k)).map(k => [k, { ...emptyProfileRow(), shape }])) }, status: null }));
  };
  const clearAll = () => {
    if (readOnly) return;
    update(s => ({ ...s, history: [...s.history.slice(-19), s.draft], future: [], draft: { ...s.draft,
      ...Object.fromEntries(keys.filter(k => !isUserLineKey(k)).map(k => [k, emptyProfileRow()])) }, status: null }));
  };
  let specNow = "";
  try { specNow = encodeSpec(keys, wireProfileDraft(keys, state.draft)); } catch { /* Ambiguous/invalid lexical input cannot be sent as a spec. */ }
  const outdated = Boolean(state.plan && (state.plan.spec !== specNow || state.plan.project !== project || state.plan.scenario !== data?.save.scenario_id || state.plan.hash !== data?.save.content_hash));
  const runPreview = () => singleFlight(async () => {
    const s = current.current, snapshot = s.data;
    if (!snapshot || snapshot.project.code !== projectRef.current || scopeMismatch || !specNow || specNow.length > 8000 || locked) return;
    const spec = specNow, askedProject = projectRef.current, askedScope = scopeOf(snapshot), ticket = ++previewTicket.current;
    previewAbort.current?.abort(); const abort = new AbortController(); previewAbort.current = abort;
    update(v => ({ ...v, busy: "preview", error: null }));
    const result = await fetchCapexPreview(askedProject, spec, abort.signal);
    if (ticket !== previewTicket.current || abort.signal.aborted || askedProject !== projectRef.current) { update(v => v.busy === "preview" ? { ...v, busy: "" } : v); return; }
    if (result.ok && result.content_hash === snapshot.save.content_hash && result.plan.months_count === snapshot.months && current.current.data && scopeOf(current.current.data) === askedScope) {
      update(v => ({ ...v, busy: "", plan: { plan: result.plan, spec, project: askedProject, scenario: snapshot.save.scenario_id, hash: result.content_hash } }));
    } else update(v => ({ ...v, busy: "", plan: null, error: { code: result.ok ? "PREVIEW_IDENTITY_CHANGED" : result.code,
      message: result.ok ? "Saved inputs changed during preview. Refresh and preview again; nothing was saved." : result.message ?? "The server preview is unavailable." } }));
  });
  const verify = (fresh: CapexProfiles, submission: Submission) => fresh.project.code === submission.project && scopeOf(fresh) === submission.scope && !fresh.saved.error && sameProfileDocument(fresh.saved.rows, submission.expected);
  const save = (action: "save" | "reset", confirmed = false) => singleFlight(async () => {
    const s = current.current, snapshot = s.data, baseline = s.baseline;
    if (!snapshot || !baseline || readOnly || lockedRef.current || externalPending || s.stale || scopeMismatch || (action === "save" && (problems.length || snapshot.saved.error || (!dirtyOf(s) && !orphans.length)))) return;
    if (action === "save" && orphans.length && !confirmed) { update(v => ({ ...v, dialog: "orphans" })); return; }
    const wire = action === "reset" ? Object.fromEntries(keys.map(k => [k, { shape: "", explicit: "", milestone: "" }])) : wireProfileDraft(keys, s.draft);
    const submission: Submission = { project, scope: scopeOf(snapshot), expected: action === "reset" ? {} : profileDocument(keys, s.draft) };
    submitted.current = submission;
    update(v => ({ ...v, busy: "save", status: null, dialog: null }));
    const outcome = await saveCapexProfile({ url: snapshot.save.url, project, csrfToken: baseline.save.csrf_token,
      contentHash: baseline.save.content_hash, action, items: keys, draft: wire });
    if (projectRef.current !== submission.project || (signal.current && `${signal.current.project}|${signal.current.scenario}` !== submission.scope)) {
      setLocked(true); update(v => ({ ...v, busy: "", status: { tone: "conflict", text: "The save belongs to the previous project/scenario. Draft retained and locked; return to that context to reconcile." } })); return;
    }
    if (outcome.kind === "unknown") { setLocked(true); update(v => ({ ...v, busy: "", status: { tone: "conflict", text: outcome.message } })); return; }
    if (outcome.kind === "refused") {
      submitted.current = null;
      update(v => ({ ...v, busy: "", stale: "The save was refused. Refresh and reconcile the retained draft before trying again.", status: { tone: "error", text: outcome.message } }));
      void load(); return;
    }
    const fresh = await load();
    if (fresh && verify(fresh, submission)) {
      submitted.current = null; setLocked(false);
      update(v => ({ ...v, busy: "", baseline: fresh, data: fresh, draft: profileDraftFromSaved(fresh), history: [], future: [], plan: null, stale: "",
        status: { tone: "ok", text: action === "reset" ? "Saved profile removed and verified in the fresh projection. The results are now STALE; the model was not run."
          : "Profile saved and verified in the fresh projection. The results are now STALE; the model was not run. Only profiles were saved, not staged line amounts or comments." } }));
      (signal.current?.onSaved ?? callback.current)?.();
    } else { setLocked(true); update(v => ({ ...v, busy: "", status: { tone: "conflict", text: "The server answered success but full shape, percentages and milestone read-back did not confirm this change. Draft retained; reconcile without resubmitting." } })); }
  });
  const reconcile = () => singleFlight(async () => {
    const fresh = await load();
    if (!fresh) return;
    const s = current.current;
    if (lockedRef.current) {
      if (submitted.current && verify(fresh, submitted.current)) {
        submitted.current = null; setLocked(false);
        update(v => ({ ...v, baseline: fresh, data: fresh, draft: profileDraftFromSaved(fresh), history: [], future: [], stale: "", plan: null,
          status: { tone: "ok", text: "The latest saved full profile matches the requested change. Verified by read-back; the model was not run." } }));
        (signal.current?.onSaved ?? callback.current)?.();
      } else update(v => ({ ...v, status: { tone: "conflict", text: "The outcome is still UNKNOWN. The retained draft does not match the saved full document. No save was retried; reload the workspace to reconcile." } }));
      return;
    }
    if (s.baseline && scopeOf(s.baseline) === scopeOf(fresh) && sameProfileDocument(s.baseline.saved.rows, fresh.saved.rows)) {
      update(v => ({ ...v, baseline: fresh, stale: "", plan: null, status: { tone: "ok", text: "The saved profile is unchanged. Draft retained against the latest inputs/token; it has not been saved. Review duration/validation and preview again." } }));
    } else update(v => ({ ...v, stale: "The saved profile or scope differs from the draft baseline. Draft retained. Review it, then explicitly discard or return to its original context; no overwrite or retry was made." }));
  });
  return { ...state, data, draft: state.draft, saved, keys, dirtyCount, orphans, problems, readOnly, editable, locked, scopeMismatch, externalPending,
    specNow, outdated, activate, syncWorkspace, reload: load, change, changeShape, undo, redo, applyBulk, clearAll, discard, runPreview, save, reconcile,
    setDialog: (dialog: State["dialog"]) => update(s => ({ ...s, dialog })) };
}

type Controller = ReturnType<typeof useController>;
const Context = createContext<Controller | null>(null);
export function CapexProfileDraftProvider({ project, children, reloadKey = 0, onSaved }: { project: string; children: ReactNode; reloadKey?: number; onSaved?: () => void }) {
  const controller = useController(project, reloadKey, onSaved);
  return <Context.Provider value={controller}>{children}<ProfileConfirm controller={controller} /></Context.Provider>;
}
export function EnsureCapexProfileDraft({ project, reloadKey, onSaved, children }: { project: string; reloadKey?: number; onSaved?: () => void; children: ReactNode }) {
  const existing = useContext(Context);
  return existing ? <>{children}</> : <CapexProfileDraftProvider project={project} reloadKey={reloadKey} onSaved={onSaved}>{children}</CapexProfileDraftProvider>;
}
export const useOptionalCapexProfileDraft = () => useContext(Context);
export function useCapexProfileDraft(activate = true) {
  const value = useContext(Context);
  if (!value) throw new Error("CAPEX profile editor requires its shared draft provider");
  const start = value.activate;
  useEffect(() => { if (activate) start(); }, [start, activate]);
  return value;
}
function ProfileConfirm({ controller: c }: { controller: Controller }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { if (c.dialog && !ref.current?.open) ref.current?.showModal(); else if (!c.dialog && ref.current?.open) ref.current.close(); }, [c.dialog]);
  return <dialog ref={ref} className="wf-dialog pr2b-confirm" data-wf-dialog={c.dialog ? "true" : undefined} aria-label={c.dialog === "reset" ? "Remove the saved profile?" : "Remove the saved profile of retired lines?"}
    onCancel={e => { e.preventDefault(); if (!c.busy) c.setDialog(null); }}>
    {c.dialog && <><h3>{c.dialog === "reset" ? "Remove the saved profile?" : "Remove profiles of inactive or retired lines?"}</h3>
      <p>{c.dialog === "reset" ? "The full saved profile will be removed. Unsaved profile edits are discarded only if you confirm. The model is not run."
        : `Saving removes ${c.orphans.length} saved or draft profile(s) whose line is no longer eligible. Cancel to retain them or reactivate the line first.`}</p>
      <button type="button" className="rx-button rx-button-secondary" disabled={Boolean(c.busy)} onClick={() => c.setDialog(null)}>Cancel</button>
      <button type="button" className="rx-button" disabled={Boolean(c.busy || c.stale || c.locked || c.scopeMismatch || !c.data?.edit.allowed)} onClick={() => void c.save(c.dialog === "reset" ? "reset" : "save", true)}>{c.dialog === "reset" ? "Remove profile" : "Save and remove"}</button></>}
  </dialog>;
}
