"use strict";
(() => {
  const button = document.getElementById("refresh");
  if (!button) return;
  let pending = false;
  button.addEventListener("click", async () => {
    if (pending) return;
    pending = true;
    button.disabled = true;
    button.textContent = "Refreshing…";
    try {
      const response = await fetch("/radar/api/snapshot", {method: "GET", cache: "no-store"});
      if (!response.ok) throw new Error("Snapshot refresh failed");
      await response.json();
      window.location.reload();
    } catch (_error) {
      button.textContent = "Refresh failed — retry";
      button.disabled = false;
      pending = false;
    }
  });
})();
