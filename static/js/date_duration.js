/* Shared Start Date + Duration -> End Date pattern (RC-UX Phase 2 / Addendum D).
 *
 * Presentation only: it never persists anything and owns no financial authority. Calendar arithmetic follows the model's own convention
 * (dateutil relativedelta, as used by the period engine): N calendar months are added to the start date; when the target month is shorter the
 * day is clamped to the last day of that month (31 Jan + 1 month = 28/29 Feb). A year is 12 calendar months, never 365 days and a month is
 * never 30 days. Durations must resolve to a whole, positive number of months.
 */
(function () {
  'use strict';
  if (window.FincoDates) return;
  const ISO = /^\d{4}-\d{2}-\d{2}$/;
  const pad = (n, w) => String(n).padStart(w, '0');
  const iso = (y, m, d) => pad(y, 4) + '-' + pad(m, 2) + '-' + pad(d, 2);
  const daysIn = (y, m) => new Date(Date.UTC(y, m, 0)).getUTCDate();                // m is 1-12
  function parse(text) {
    if (typeof text !== 'string' || !ISO.test(text)) return null;
    const y = +text.slice(0, 4), m = +text.slice(5, 7), d = +text.slice(8, 10);
    if (m < 1 || m > 12 || d < 1 || d > daysIn(y, m)) return null;
    return {y, m, d};
  }
  function addMonths(text, months) {
    const p = parse(text);
    if (!p || !Number.isInteger(months)) return null;
    const index = p.y * 12 + (p.m - 1) + months;
    const y = Math.floor(index / 12), m = (index % 12 + 12) % 12 + 1;
    return iso(y, m, Math.min(p.d, daysIn(y, m)));
  }
  function monthsOf(value, unit) {
    const t = String(value == null ? '' : value).trim();
    if (!/^\d+(\.\d+)?$/.test(t)) return null;                                      // no sign, no comma, no text
    const n = Number(t) * (unit === 'years' ? 12 : 1);
    return Number.isFinite(n) && Math.abs(n - Math.round(n)) < 1e-9 && Math.round(n) > 0 ? Math.round(n) : null;
  }
  // Exact whole-month difference when `end` is reachable from `start` by addMonths (else null).
  function impliedMonths(start, end) {
    const a = parse(start), b = parse(end);
    if (!a || !b) return null;
    const n = (b.y - a.y) * 12 + (b.m - a.m);
    return n > 0 && addMonths(start, n) === end ? n : null;
  }
  const describe = (n) => n % 12 === 0 ? (n / 12) + (n === 12 ? ' year' : ' years') : n + (n === 1 ? ' month' : ' months');

  function mount(root) {
    if (!root || root.dataset.ddReady === 'true') return;
    root.dataset.ddReady = 'true';
    const q = (name) => root.querySelector('[data-dd="' + name + '"]');
    const start = q('start'), duration = q('duration'), unit = q('unit'), end = q('end'), manual = q('manual'), reset = q('reset'), note = q('note');
    if (!start || !duration || !unit || !end || !manual) return;
    const state = () => {
      const months = monthsOf(duration.value, unit.value);
      const isManual = manual.checked;
      const value = end.value;
      let message = '';
      if (!parse(start.value)) message = 'Enter a valid start date.';
      else if (!isManual && months === null) message = 'Enter a positive duration that is a whole number of months (for example 15 years or 18 months).';
      else if (!parse(value)) message = isManual ? 'Enter a valid end date.' : 'The end date could not be calculated.';
      else if (value <= start.value) message = 'The end date must be after the start date.';
      return {start: start.value, end: value, months: isManual ? impliedMonths(start.value, value) : months, manual: isManual, valid: !message, message};
    };
    const emit = () => root.dispatchEvent(new CustomEvent('dd:change', {bubbles: true, detail: state()}));
    function recalc() {
      const months = monthsOf(duration.value, unit.value);
      if (!manual.checked) {
        end.readOnly = true;
        end.value = months !== null && parse(start.value) ? addMonths(start.value, months) : '';
      } else {
        end.readOnly = false;
      }
      const s = state();
      if (note) {
        const clamped = !manual.checked && months !== null && parse(start.value) && parse(end.value) && parse(start.value).d !== parse(end.value).d;
        note.textContent = manual.checked
          ? 'Automatic end-date calculation is off.' + (s.months ? ' This end date equals ' + describe(s.months) + ' from the start.' : ' This end date is not a whole number of months from the start.')
          : (clamped ? 'Month-end adjusted: the end falls on the last day of a shorter month.' : '');
      }
      if (reset) reset.hidden = !manual.checked;
      end.setAttribute('aria-readonly', String(end.readOnly));
      emit();
    }
    [start, duration, unit].forEach(el => el.addEventListener('input', recalc));
    unit.addEventListener('change', recalc);
    end.addEventListener('input', () => { if (manual.checked) recalc(); });
    manual.addEventListener('change', () => {
      if (manual.checked && s0(end.value)) { /* keep the calculated date as the first editable value */ }
      recalc();
    });
    if (reset) reset.addEventListener('click', () => { manual.checked = false; recalc(); end.focus(); });
    function s0(v) { return !!v; }
    root.ddState = state;
    root.ddRecalc = recalc;
    recalc();
  }
  function scan() { document.querySelectorAll('[data-dd-root]').forEach(mount); }
  document.addEventListener('DOMContentLoaded', scan);
  document.addEventListener('htmx:afterSettle', scan);
  window.FincoDates = {addMonths, monthsOf, impliedMonths, parse, mount, scan, describe};
  scan();
})();
