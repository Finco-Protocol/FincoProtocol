/** G10 Last-Run panel — request lifecycle gate (pure, node-testable).
 *
 * Guarantees: exactly one live request per gate; starting a new request aborts the previous one and
 * returns a strictly increasing identity; `isCurrent` accepts a settled result only when the identity
 * it was fetched for is STILL the gate's current one — an out-of-order or stale response can therefore
 * never be applied, and data fetched for project A can never render under project B. */

export interface RequestIdentity {
  project: string;
  reloadKey: number;
  seq: number;
}

export class RequestGate {
  private seq = 0;
  private current: RequestIdentity | null = null;
  private controller: AbortController | null = null;

  begin(project: string, reloadKey: number): { identity: RequestIdentity; signal: AbortSignal } {
    this.seq += 1;
    if (this.controller) this.controller.abort();
    this.controller = new AbortController();
    this.current = { project, reloadKey, seq: this.seq };
    return { identity: { ...this.current }, signal: this.controller.signal };
  }

  identity(): RequestIdentity | null {
    return this.current ? { ...this.current } : null;
  }

  isCurrent(identity: RequestIdentity): boolean {
    return (
      this.current !== null &&
      this.current.project === identity.project &&
      this.current.reloadKey === identity.reloadKey &&
      this.current.seq === identity.seq
    );
  }

  cancel(): void {
    if (this.controller) this.controller.abort();
    this.controller = null;
    this.current = null;
  }
}
