"use strict";

(() => {
  const panel = document.getElementById("r-live-aapl");
  if (!panel) return;
  const field = (name) => panel.querySelector(`[data-r-live="${name}"]`);
  const set = (name, value) => { field(name).textContent = value ?? ""; };
  const history = field("history");

  async function load() {
    // Clear current values before the request: a failed refresh must fail closed.
    panel.dataset.state = "UNAVAILABLE";
    set("state", "UNAVAILABLE");
    set("age", "");
    set("reference", "");
    set("basis", "");
    set("premium", "");
    field("values").hidden = true;
    set("reason", "Fresh evidence is not available.");
    try {
      const response = await fetch("/radar/crypto/rwa/r-live/aapl/snapshot", { cache: "no-store" });
      if (!response.ok) return;
      const data = await response.json();
      const state = ["AVAILABLE", "STALE", "UNAVAILABLE"].includes(data.state) ? data.state : "UNAVAILABLE";
      panel.dataset.state = state;
      set("state", state);
      if (state !== "AVAILABLE" || !data.reference || !data.reference_premium?.value_bps) {
        set("reason", data.reason || "Fresh evidence is not available.");
        return;
      }
      set("reference", data.reference.priceUsdPerToken);
      set("basis", data.robinhood_basis.price_usd_per_token);
      set("premium", data.reference_premium.value_bps);
      set("age", `observed ${data.observation_age_seconds}s ago · ${data.observed_at}`);
      set("reason", "Direct On-Chain observation; no trading or execution signal.");
      field("values").hidden = false;

      const uid = data.reference.assetUid;
      const key = data.reference.assetKey;
      if (!uid || !key?.startsWith("4663:")) return;
      const query = new URLSearchParams({ economic_asset_uid: uid, contract_address: key.slice(5) });
      const prior = await fetch(`/radar/crypto/rwa/r-live/aapl/history?${query}`, { cache: "no-store" });
      if (!prior.ok) return;
      const points = (await prior.json()).points;
      history.replaceChildren();
      for (const point of points.slice(0, 5)) {
        const row = document.createElement("li");
        row.textContent = `${point.observed_at} — ${point.reference_premium_bps} bps (historical)`;
        history.append(row);
      }
      if (!points.length) {
        const row = document.createElement("li");
        row.textContent = "No historical premium observations.";
        history.append(row);
      }
    } catch (_) {
      panel.dataset.state = "UNAVAILABLE";
      set("state", "UNAVAILABLE");
      field("values").hidden = true;
      set("reason", "Fresh evidence is not available.");
    }
  }

  load();
  window.setInterval(load, 60000);
})();
