/* Ephemeral candidate input serialization only; all physics is server-side. */
(function () {
  'use strict';
  const form = document.querySelector('[data-testid="bess-review-form"]');
  if (!form || form.querySelector('fieldset[disabled]')) return;
  const payload = form.querySelector('[data-m7-payload]');
  const book = JSON.parse(payload.value);
  const events = form.querySelector('[data-m7-events]');
  const error = form.querySelector('[data-m7-error]');
  function timestamp(value) { return value.length === 16 ? value + ':00Z' : value + 'Z'; }
  function eventRow(row) {
    const line = document.createElement('div'); line.className = 'm7-fields'; line.dataset.m7Event = '';
    const specs = [['at', 'Event UTC', 'datetime-local'], ['kind', 'Event', 'select'], ['installed_energy_mwh', 'Installed MWh', 'number'],
      ['usable_energy_mwh', 'Usable MWh', 'number'], ['cost_keur', 'Paid CAPEX kEUR', 'number'],
      ['useful_life_years', 'Physical useful life years', 'number'], ['source_ref', 'Event source', 'text']];
    for (const [key, title, type] of specs) {
      const label = document.createElement('label'); label.textContent = title;
      const input = document.createElement(type === 'select' ? 'select' : 'input');
      input.dataset.m7EventField = key; input.required = true;
      if (type === 'select') {
        for (const value of ['', 'AUGMENT', 'REPLACE']) { const option = document.createElement('option'); option.value = value; option.textContent = value || 'Select'; input.appendChild(option); }
      } else {
        input.type = type; if (type === 'number') { input.min = '0'; input.step = key === 'useful_life_years' ? '1' : 'any'; }
        if (type === 'datetime-local') input.step = '3600';
      }
      input.value = key === 'at' ? (row[key] || '').replace('Z', '') : row[key] ?? '';
      label.appendChild(input); line.appendChild(label);
    }
    const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = 'Remove event';
    remove.addEventListener('click', () => line.remove()); line.appendChild(remove); events.appendChild(line);
  }
  book.events.forEach(eventRow);
  form.querySelector('[data-m7-add-event]').addEventListener('click', () => eventRow({}));
  form.addEventListener('submit', event => {
    try {
      for (const input of form.querySelectorAll('[data-m7-battery]')) {
        const value = Number(input.value);
        if (!input.value || !Number.isFinite(value)) throw Error('Supply finite numeric assumptions.');
        book.battery[input.dataset.m7Battery] = input.dataset.fraction === 'true' ? value / 100 : value;
      }
      for (const input of form.querySelectorAll('[data-m7-root]')) book[input.dataset.m7Root] =
        input.type === 'datetime-local' ? timestamp(input.value) : input.value;
      for (const row of form.querySelectorAll('[data-m7-point]')) {
        const target = book.dispatch[Number(row.dataset.m7Point)];
        for (const input of row.querySelectorAll('[data-m7-point-field]')) target[input.dataset.m7PointField] =
          input.type === 'checkbox' ? input.checked : input.type === 'number' ? Number(input.value) : input.value;
      }
      book.events = [...events.querySelectorAll('[data-m7-event]')].map(row => {
        const value = {tax_book_policy:'UNRESOLVED'};
        for (const input of row.querySelectorAll('[data-m7-event-field]')) value[input.dataset.m7EventField] =
          input.type === 'datetime-local' ? timestamp(input.value) : input.type === 'number' ? Number(input.value) : input.value;
        return value;
      });
      payload.value = JSON.stringify(book);
    } catch (exc) { event.preventDefault(); error.hidden = false; error.textContent = exc.message; }
  });
  form.querySelector('[data-m7-validate]').disabled = false;
})();
