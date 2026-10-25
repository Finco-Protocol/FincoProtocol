import assert from "node:assert/strict";
import test from "node:test";
import {
  getDemoStorageSnapshot,
  persistDemoSessionBatch,
  probeDemoSessionStorage,
  readDemoSessionValue,
  resetDemoStorageSnapshotForTests,
  writeDemoSessionValue,
} from "./demoSessionStorage.ts";

class MemoryStorage {
  values = new Map();
  failGet = false;
  failSetKey = null;

  getItem(key) {
    if (this.failGet) throw new Error("Blocked read");
    return this.values.get(key) ?? null;
  }

  setItem(key, value) {
    if (key === this.failSetKey) throw new Error("Blocked write");
    this.values.set(key, String(value));
  }

  removeItem(key) {
    this.values.delete(key);
  }
}

test("storage probe confirms a healthy tab and cleans up its marker", () => {
  resetDemoStorageSnapshotForTests();
  const storage = new MemoryStorage();

  assert.equal(probeDemoSessionStorage(storage), true);
  assert.deepEqual(getDemoStorageSnapshot(), { state: "available", operation: "check" });
  assert.equal(storage.values.size, 0);
});

test("blocked reads are reported as unavailable, not as empty saved state", () => {
  resetDemoStorageSnapshotForTests();
  const storage = new MemoryStorage();
  storage.failGet = true;

  assert.deepEqual(readDemoSessionValue("draft", storage), { ok: false, value: null });
  assert.equal(probeDemoSessionStorage(storage), false);
  assert.deepEqual(getDemoStorageSnapshot(), { state: "unavailable", operation: "check" });
});

test("a failed single write is not acknowledged as saved", () => {
  resetDemoStorageSnapshotForTests();
  const storage = new MemoryStorage();
  storage.failSetKey = "saved";

  assert.equal(writeDemoSessionValue("saved", { amount: 8 }, storage), false);
  assert.equal(storage.getItem("saved"), null);
  assert.equal(getDemoStorageSnapshot().state, "unavailable");
});

test("batch save verifies every key and rolls back an earlier write after a later failure", () => {
  resetDemoStorageSnapshotForTests();
  const storage = new MemoryStorage();
  storage.setItem("finco-design-demo:v2:PRJ-1:first", "old");
  storage.setItem("finco-design-demo:v2:PRJ-1:second", "kept");
  storage.failSetKey = "finco-design-demo:v2:PRJ-1:second";

  assert.equal(persistDemoSessionBatch("PRJ-1", [["first", "new"], ["second", "new"]], "working-copy", storage), false);
  assert.equal(storage.getItem("finco-design-demo:v2:PRJ-1:first"), "old");
  assert.equal(storage.getItem("finco-design-demo:v2:PRJ-1:second"), "kept");
  assert.equal(getDemoStorageSnapshot().state, "unavailable");
});

test("verified batch save is scoped to the working copy; Reference is never writable", () => {
  resetDemoStorageSnapshotForTests();
  const storage = new MemoryStorage();

  assert.equal(persistDemoSessionBatch("PRJ-1", [["scalar-saved", { value: "12" }]], "working-copy", storage), true);
  assert.equal(storage.getItem("finco-design-demo:v2:PRJ-1:scalar-saved"), "{\"value\":\"12\"}");
  assert.equal(persistDemoSessionBatch("PRJ-1", [["scalar-saved", { value: "13" }]], "reference", storage), false);
  assert.equal(storage.getItem("finco-design-demo:v2:PRJ-1:reference:scalar-saved"), null);
});
