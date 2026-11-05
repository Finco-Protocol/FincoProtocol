/** Node tests for the G10 Last-Run panel request gate: stale/out-of-order responses can never be applied. */
import test from "node:test";
import assert from "node:assert/strict";

import { RequestGate } from "../opexRunRequest.ts";

test("begin returns strictly increasing identities and aborts the previous request", () => {
  const gate = new RequestGate();
  const a = gate.begin("project-a", 0);
  assert.equal(a.identity.seq, 1);
  assert.equal(a.identity.project, "project-a");
  const b = gate.begin("project-b", 0);
  assert.equal(b.identity.seq, 2);
  assert.equal(a.signal.aborted, true, "the superseded request must be aborted");
  assert.equal(b.signal.aborted, false);
});

test("isCurrent accepts only the exact current identity", () => {
  const gate = new RequestGate();
  const first = gate.begin("a", 0);
  assert.equal(gate.isCurrent(first.identity), true);
  const second = gate.begin("b", 0);
  assert.equal(gate.isCurrent(first.identity), false, "stale project identity is not current");
  assert.equal(gate.isCurrent(second.identity), true);
  const third = gate.begin("b", 1);
  assert.equal(gate.isCurrent(second.identity), false, "same project, older reloadKey is not current");
  assert.equal(gate.isCurrent(third.identity), true);
});

test("cancel invalidates everything", () => {
  const gate = new RequestGate();
  const req = gate.begin("a", 3);
  gate.cancel();
  assert.equal(req.signal.aborted, true);
  assert.equal(gate.isCurrent(req.identity), false);
  assert.equal(gate.identity(), null);
});

test("rapid A→B→A: only the last identity is current, earlier ones are stale", () => {
  const gate = new RequestGate();
  const ids = [gate.begin("a", 0), gate.begin("b", 0), gate.begin("a", 0)];
  assert.equal(gate.isCurrent(ids[0].identity), false);
  assert.equal(gate.isCurrent(ids[1].identity), false);
  assert.equal(gate.isCurrent(ids[2].identity), true);
  assert.notEqual(ids[0].identity.seq, ids[2].identity.seq, "A after B is a NEW request, not the old one");
});
