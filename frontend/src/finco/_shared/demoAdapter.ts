/**
 * Isolated adapter contract spike for tests/documentation only.
 * It is not imported by the FINCO preview UI and makes no network calls.
 * Names and envelope fields below are sandbox-only examples, not verified API DTOs.
 */
export type DemoFreshness = "CURRENT" | "STALE" | "UNKNOWN";
export type DemoIntegrity = "NOT_EVALUATED";
export type DemoEngineCurrency = "CURRENT" | "STALE" | "UNKNOWN";
export type DemoRunSelection = "NONE" | "LAST" | "HISTORICAL";

export type DemoStatementValue =
  | { availability: "available"; value: number; unit: string }
  | { availability: "unavailable"; reason: string };

export type DemoLastRun = {
  runId: string;
  revision: string;
  engineVersion: string | null;
  statementValue: DemoStatementValue;
};

export type DemoAdapterState = {
  projectId: string;
  fieldId: string;
  scenarioId: string;
  editable: boolean;
  draftValue: string;
  committedValue: string;
  revision: string;
  latestRequestId: number;
  lastRun: DemoLastRun | null;
  runSelection: DemoRunSelection;
  engineCurrency: DemoEngineCurrency;
  freshness: DemoFreshness;
  integrity: DemoIntegrity;
  saveState: "CLEAN" | "UNSAVED" | "DEMO_SAVED" | "VALIDATION_ERROR" | "CONFLICT" | "READ_ONLY" | "AUTH_REJECTED" | "CONTEXT_MISMATCH" | "STALE_RESPONSE" | "TRANSPORT_ERROR";
  message: string;
};

export type DemoSaveRequest = {
  projectId: string;
  fieldId: string;
  scenarioId: string;
  value: string;
  expectedRevision: string;
  requestId: number;
};

export type DemoSaveResponse =
  | { status: "saved"; revision: string; projectId?: string; scenarioId?: string }
  | { status: "invalid"; message: string }
  | { status: "unprocessable_entity"; message: string }
  | { status: "conflict"; currentRevision: string }
  | { status: "unauthorized"; message?: string }
  | { status: "forbidden"; message?: string };

export type DemoTransport = {
  saveField(request: DemoSaveRequest): Promise<DemoSaveResponse>;
};

export function beginDemoSave(state: DemoAdapterState): {
  state: DemoAdapterState;
  request: DemoSaveRequest;
} {
  const requestId = state.latestRequestId + 1;
  return {
    state: { ...state, latestRequestId: requestId, saveState: "UNSAVED" },
    request: {
      projectId: state.projectId,
      fieldId: state.fieldId,
      scenarioId: state.scenarioId,
      value: state.draftValue,
      expectedRevision: state.revision,
      requestId,
    },
  };
}

/**
 * Apply a fake response to the latest owner state. Older responses and
 * mismatched scenario contexts are surfaced without replacing the typed draft.
 */
export function applyDemoSaveResponse(
  current: DemoAdapterState,
  request: DemoSaveRequest,
  response: DemoSaveResponse,
): DemoAdapterState {
  if (request.requestId !== current.latestRequestId) {
    return {
      ...current,
      saveState: "STALE_RESPONSE",
      message: "Out-of-order demo response ignored; the latest draft was preserved.",
    };
  }

  if (request.projectId !== current.projectId ||
      (response.status === "saved" && response.projectId !== undefined && response.projectId !== current.projectId) ||
      request.scenarioId !== current.scenarioId ||
      (response.status === "saved" && response.scenarioId !== undefined && response.scenarioId !== current.scenarioId)) {
    return {
      ...current,
      saveState: "CONTEXT_MISMATCH",
      message: "Demo response context did not match the selected project or scenario; no value was acknowledged.",
    };
  }

  if (response.status === "unauthorized" || response.status === "forbidden") {
    return {
      ...current,
      saveState: "AUTH_REJECTED",
      message: response.message || "Fake transport rejected the request; no value was acknowledged.",
    };
  }

  if (response.status === "invalid" || response.status === "unprocessable_entity") {
    return { ...current, saveState: "VALIDATION_ERROR", message: response.message };
  }

  if (response.status === "conflict") {
    return {
      ...current,
      freshness: "STALE",
      saveState: "CONFLICT",
      message: `Revision conflict. Current demo revision is ${response.currentRevision}; draft value was retained.`,
    };
  }

  const newerDraftRemains = current.draftValue !== request.value;
  return {
    ...current,
    committedValue: request.value,
    revision: response.revision,
    freshness: current.lastRun
      ? current.lastRun.revision === response.revision
        ? "CURRENT"
        : "STALE"
      : "UNKNOWN",
    saveState: newerDraftRemains ? "UNSAVED" : "DEMO_SAVED",
    message: newerDraftRemains
      ? "The submitted draft was acknowledged; a newer typed value remains unsaved. No Run was invoked."
      : "Demo transport acknowledged Save only. No Run was invoked.",
  };
}

export async function saveDemoField(
  state: DemoAdapterState,
  transport: DemoTransport,
): Promise<DemoAdapterState> {
  if (!state.editable) {
    return { ...state, saveState: "READ_ONLY", message: "Reference values are read-only." };
  }

  const attempt = beginDemoSave(state);
  try {
    const response = await transport.saveField(attempt.request);
    return applyDemoSaveResponse(attempt.state, attempt.request, response);
  } catch {
    return {
      ...attempt.state,
      saveState: "TRANSPORT_ERROR",
      message: "Fake transport failed. The typed draft was preserved; no retry was attempted.",
    };
  }
}

export function formatDemoStatementValue(value: DemoStatementValue | null | undefined): string {
  if (value == null) return "— (missing)";
  if (value.availability === "unavailable") return `— (${value.reason})`;
  return `${value.value} ${value.unit}`.trim();
}
