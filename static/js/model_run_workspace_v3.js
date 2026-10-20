/* Run Workspace V3 selector synchronization — presentation only.
 * The server remains authoritative for every requested Run and reference.
 * This helper only prevents stale dropdown choices during normal edits.
 */
(() => {
  "use strict";
  const root = document.querySelector('[data-testid="run-workspace-v3"]');
  if (!root || root.dataset.referenceSyncBound === "1") return;
  const form = root.querySelector('[data-testid="rw-selector"]');
  if (!form) return;
  const slots = Array.from(form.querySelectorAll('select[name="run"]'));
  const reference = form.querySelector('select[name="reference"]');
  if (slots.length !== 3 || !reference) return;
  root.dataset.referenceSyncBound = "1";

  const sync = () => {
    const previous = reference.value;
    const offered = new Set();
    const choices = [];
    slots.forEach((slot, index) => {
      const id = slot.value;
      if (!id || offered.has(id)) return;
      offered.add(id);
      const chosen = slot.selectedOptions[0];
      choices.push({id, label: "Run " + (index + 1) + " · " +
        (chosen ? chosen.textContent.trim() : id)});
    });
    reference.replaceChildren();
    choices.forEach(choice => {
      const option = document.createElement("option");
      option.value = choice.id;
      option.textContent = choice.label;
      reference.appendChild(option);
    });
    if (offered.has(previous)) reference.value = previous;
    else if (choices.length) reference.value = choices[0].id;
    // No valid choices: leave reference empty. The server will show the
    // existing no-comparison state; it never invents missing Run results.
    if (choices.length === 0) reference.value = "";
  };
  slots.forEach(slot => slot.addEventListener("change", sync));
  sync();
})();
