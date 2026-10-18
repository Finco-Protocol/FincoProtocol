/* WF-11: transient, non-persistent OPEX candidate previews only.
 * Never writes a canonical input, starts a Run or stores user input.
 */
(function () {
  "use strict";
  if (window.__wf11OpexEventsBound) return;
  window.__wf11OpexEventsBound = true;
  const records = new WeakMap();
  const scalar = (value, code) => {
    const raw = String(value).trim();
    if (!/^(?:0|[1-9]\d*)(?:\.\d{1,6})?$/.test(raw)) throw new Error(code);
    const num = Number(raw);
    if (!Number.isFinite(num) || num < 0 || num > 1e12) throw new Error(code);
    return num;
  };
  const integer = (value, max, code) => {
    const raw = String(value).trim();
    if (!/^[1-9]\d*$/.test(raw) || Number(raw) > max) throw new Error(code);
    return Number(raw);
  };
  function cell(row, value, header) {
    const el = document.createElement(header ? 'th' : 'td');
    if (header) el.scope = 'row';
    el.textContent = String(value);
    row.appendChild(el);
    return el;
  }
  const yearsOf = (event, max) => {
    const result = [];
    for (let y = event.year; y <= max; y += (event.recurrence === 'ONE_OFF' ? max + 1 : event.interval)) result.push(y);
    return result;
  };
  function paintEvents(root) {
    const rows = root.querySelector('[data-wf11-event-rows]');
    if (!rows) return;
    rows.replaceChildren();
    const events = records.get(root) || [];
    if (!events.length) { const tr = rows.insertRow(); const td = cell(tr, 'No events proposed.'); td.colSpan = 6; return; }
    events.forEach((event, index) => {
      const tr = document.createElement('tr');
      cell(tr, event.id, true); cell(tr, event.owner);
      cell(tr, yearsOf(event, Number(root.dataset.maxYear)).join(', '));
      cell(tr, event.amount.toFixed(2)); cell(tr, event.classification);
      const action = document.createElement('td');
      const remove = document.createElement('button');
      remove.type = 'button'; remove.textContent = 'Remove candidate';
      remove.dataset.wf11Remove = String(index);
      action.appendChild(remove); tr.appendChild(action); rows.appendChild(tr);
    });
  }
  document.addEventListener('change', function (event) {
    const f = event.target.closest('[data-wf11-maintenance]');
    if (!f || event.target.name !== 'recurrence') return;
    f.elements.interval.disabled = f.elements.recurrence.value !== 'EVERY_N_YEARS';
  });
  document.addEventListener('click', function (event) {
    const btn = event.target.closest('[data-wf11-remove]');
    if (!btn) return;
    const root = btn.closest('[data-wf11-candidate]');
    if (!root) return;
    const events = records.get(root) || [];
    events.splice(Number(btn.dataset.wf11Remove), 1);
    paintEvents(root);
    root.querySelector('[data-wf11-status]').textContent = 'Unsaved proposal removed. Run unchanged.';
  });
  document.addEventListener('submit', function (event) {
    const f = event.target;
    if (!f.matches('[data-wf11-maintenance], [data-wf11-seasonal]')) return;
    event.preventDefault(); // candidate forms NEVER send data to the server
    const root = f.closest('[data-wf11-candidate]');
    if (!root) return;
    const max = Number(root.dataset.maxYear);
    if (!Number.isInteger(max) || max < 1 || max > 60) return;
    if (f.matches('[data-wf11-maintenance]')) {
      const message = root.querySelector('[data-wf11-status]');
      try {
        const id = f.elements.event_id.value.trim();
        if (!/^[A-Za-z0-9_-]{1,64}$/.test(id)) throw new Error('EVENT_ID_INVALID');
        const owner = f.elements.owner_line.value;
        if (!/^B\.(?:0[1-9]|1[0-2])(?:\.(?:\d{2}|U\d{3}))?$/.test(owner)
          || !Array.from(f.elements.owner_line.options).some(x => x.value === owner)) throw new Error('OWNER_NOT_ALLOWED');
        const year = integer(f.elements.year.value, max, 'YEAR_OUT_OF_HORIZON');
        const amount = scalar(f.elements.amount.value, 'AMOUNT_INVALID');
        const recurrence = f.elements.recurrence.value;
        if (!['ONE_OFF', 'EVERY_N_YEARS'].includes(recurrence)) throw new Error('RECURRENCE_INVALID');
        const interval = recurrence === 'ONE_OFF' ? null : integer(f.elements.interval.value, max, 'RECURRENCE_INVALID');
        const classification = f.elements.classification.value;
        if (!['UNRESOLVED', 'OPEX_EXPENSE_PROPOSED', 'CAPITAL_REPLACEMENT_REVIEW'].includes(classification)) throw new Error('CLASSIFICATION_INVALID');
        const candidate = { id, owner, year, amount, recurrence, interval, classification };
        const items = records.get(root) || [];
        if (items.length >= 60) throw new Error('EVENT_LIMIT');
        if (items.some(x => x.id === id)) throw new Error('DUPLICATE_EVENT_ID');
        const occupied = new Set(items.flatMap(x => yearsOf(x, max).map(y => x.owner + ':' + y)));
        if (yearsOf(candidate, max).some(y => occupied.has(owner + ':' + y))) throw new Error('DOUBLE_COUNTING_RISK');
        items.push(candidate);
        records.set(root, items);
        paintEvents(root);
        message.textContent = 'Preview only: financial classification and baseline overlap need approval. Not saved or included in Run.';
      } catch (err) { message.textContent = 'Candidate rejected: ' + err.message + '. No inputs changed.'; }
    } else {
      const status = root.querySelector('[data-wf11-seasonal-status]');
      const tbody = root.querySelector('[data-wf11-seasonal-output]');
      try {
        const opt = f.elements.seasonal_line.selectedOptions[0];
        if (!opt || !opt.value || !opt.dataset.years) throw new Error('LINE_REQUIRED');
        const year = integer(f.elements.seasonal_year.value, max, 'YEAR_OUT_OF_HORIZON');
        const values = opt.dataset.years.split(',');
        if (year > values.length) throw new Error('YEAR_NOT_PROJECTED');
        const annual = scalar(values[year - 1], 'ANNUAL_VALUE_UNAVAILABLE');
        const h1 = scalar(f.elements.h1.value, 'H1_WEIGHT_INVALID');
        const h2 = scalar(f.elements.h2.value, 'H2_WEIGHT_INVALID');
        if (Math.abs(h1 + h2 - 100) > 1e-9) throw new Error('WEIGHTS_MUST_TOTAL_100');
        // Presentation-only full-year percentage allocation. NO canonical stub assumptions.
        const first = annual * h1 / 100;
        const second = annual - first;
        tbody.replaceChildren();
        const tr = tbody.insertRow();
        cell(tr, annual.toFixed(4), true); cell(tr, first.toFixed(4));
        cell(tr, second.toFixed(4)); cell(tr, (first + second).toFixed(4));
        status.textContent = 'Candidate full-year allocation only. Stub dates, real half-year day fractions and Run effects NOT VERIFIED.';
      } catch (err) { status.textContent = 'Candidate rejected: ' + err.message + '. No inputs changed.'; }
    }
  });
})();
