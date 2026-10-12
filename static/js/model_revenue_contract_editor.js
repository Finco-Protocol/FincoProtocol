/* Revenue V2 structured contract editor.
 * Client-side presentation/serialization only. The existing POST endpoint, CSRF,
 * owner checks, composite CAS and canonical Python validator remain authoritative.
 */
(function () {
  'use strict';
  if (window.__fincoRevenueContractEditorV1) return;
  window.__fincoRevenueContractEditorV1 = true;

  const ROOT_KEYS = ['version', 'technology', 'indexation_basis', 'streams'];
  const BASE_KEYS = ['id', 'type', 'start_date', 'end_date', 'volume_share',
    'price_eur_mwh', 'indexation_rate', 'settlement', 'source_ref'];
  const OPTIONAL_KEYS = ['capture_rate', 'reference_stream_id', 'price_curve'];
  const KINDS = [
    ['fixed_ppa', 'Fixed PPA'], ['indexed_ppa', 'Indexed PPA'],
    ['merchant', 'Merchant'], ['residual_merchant', 'Residual Merchant'],
    ['scheduled_ppa', 'Scheduled PPA'], ['scheduled_merchant', 'Scheduled Merchant'],
    ['cfd', 'Two-way CfD']
  ];
  const labelFor = (kind) => KINDS.find(([k]) => k === kind)?.[1] || 'Unsupported';
  const isMerchant = (kind) => ['merchant', 'residual_merchant', 'scheduled_merchant'].includes(kind);
  const isScheduled = kind => ['scheduled_ppa', 'scheduled_merchant'].includes(kind);
  const toPct = (n) => n === null ? '' : String(Number((n * 100).toPrecision(12)));
  const fromPct = (text) => text.trim() === '' ? '' : Number(text) / 100;
  const legalKeys = (value, keys) => value && typeof value === 'object' &&
    !Array.isArray(value) && Object.keys(value).every((k) => keys.includes(k));
  const displayKind = (row) => Array.isArray(row.price_curve)
    ? (row.type === 'ppa' ? 'scheduled_ppa' : 'scheduled_merchant')
    : row.type === 'ppa'
      ? (row.indexation_rate > 0 ? 'indexed_ppa' : 'fixed_ppa')
      : row.type === 'merchant'
        ? (row.volume_share === null ? 'residual_merchant' : 'merchant') : 'cfd';

  function safeBook(raw, technology) {
    if (!['solar', 'wind'].includes(technology)) throw Error('Only Solar and Wind revenue contracts are supported.');
    const book = raw ? JSON.parse(raw) :
      {version: 1, technology, indexation_basis: 'OPERATING_YEAR', streams: []};
    if (!legalKeys(book, ROOT_KEYS) || ROOT_KEYS.some(k => !(k in book)) ||
        ![1, 2].includes(book.version) || book.technology !== technology ||
        book.indexation_basis !== 'OPERATING_YEAR' || !Array.isArray(book.streams) ||
        book.streams.length > 24) {
      throw Error('Existing contract configuration cannot be represented safely. No changes have been made.');
    }
    for (const row of book.streams) {
      if (!legalKeys(row, BASE_KEYS.concat(OPTIONAL_KEYS)) ||
          BASE_KEYS.some(k => !(k in row)) || !['ppa', 'merchant', 'cfd'].includes(row.type) ||
          row.settlement !== 'SAME_PERIOD' ||
          (row.type !== 'merchant' && 'capture_rate' in row) ||
          (row.type !== 'cfd' && 'reference_stream_id' in row) ||
          ('price_curve' in row && (book.version !== 2 || row.type === 'cfd' ||
            !Array.isArray(row.price_curve) || row.indexation_rate !== 0 ||
            row.price_curve.length > 600 || row.price_curve.some(point =>
              !legalKeys(point, ['period_start', 'price_eur_mwh']) ||
              !('period_start' in point) || !('price_eur_mwh' in point))))) {
        throw Error('An existing stream contains unsupported terms. Editing is blocked to preserve it.');
      }
    }
    return book;
  }

  function newRow(kind) {
    const row = {id: '', type: kind === 'cfd' ? 'cfd' : isMerchant(kind) ? 'merchant' : 'ppa',
      start_date: '', end_date: '', volume_share: kind === 'residual_merchant' ? null : 0,
      price_eur_mwh: 0, indexation_rate: 0, settlement: 'SAME_PERIOD', source_ref: ''};
    if (kind === 'cfd') row.reference_stream_id = '';
    if (isScheduled(kind)) row.price_curve = [];
    return row;
  }

  function begin(form) {
    if (form.dataset.revenueReady === 'true' || form.dataset.readonly === 'true') return;
    form.dataset.revenueReady = 'true';
    const source = form.querySelector('[data-revenue-source]');
    const payload = form.querySelector('[data-revenue-payload]');
    const tbody = form.querySelector('[data-revenue-rows]');
    const feedback = form.querySelector('[data-revenue-feedback]');
    const error = form.querySelector('[data-revenue-error]');
    const save = form.querySelector('[data-revenue-save]');
    const empty = form.querySelector('[data-revenue-empty]');
    const advancedBtn = form.querySelector('[data-revenue-advanced]');
    const raw = source.value.trim();
    let book, blocked = false, dirty = false, advanced = false, baseline = '';
    const kindOverrides = new WeakMap();

    function showError(message) {
      error.textContent = message;
      error.hidden = !message;
      if (message) feedback.textContent = 'Not saved · Review the contract details';
    }
    function status() {
      dirty = JSON.stringify(book) !== baseline;
      form.dataset.dirty = String(dirty);
      feedback.dataset.dirty = String(dirty);
      feedback.textContent = dirty ? 'Unsaved changes · Save contracts to update Working Copy (Run separately)' :
        'Saved Working Copy · No changes';
      save.disabled = !dirty || blocked;
    }
    function advancedMode(enabled) {
      advanced = !!enabled;
      form.querySelectorAll('[data-revenue-advanced-cell]').forEach(cell => { cell.hidden = !advanced; });
      advancedBtn.setAttribute('aria-expanded', String(advanced));
      advancedBtn.textContent = advanced ? 'Hide advanced terms' : 'Show advanced terms';
    }
    function setCell(tr, field, input, applicable = true, advancedCell = false) {
      const td = document.createElement('td');
      if (advancedCell) {
        td.setAttribute('data-revenue-advanced-cell', '');
        td.hidden = !advanced;
      }
      td.dataset.label = field;
      if (applicable) td.appendChild(input);
      else {
        td.className = 'rc-na';
        td.textContent = '—';
      }
      tr.appendChild(td);
      return td;
    }
    function entry(tr, index, field, value, opts = {}) {
      const input = document.createElement('input');
      input.type = opts.type || 'text';
      input.dataset.field = field;
      input.setAttribute('aria-label', opts.label || field);
      input.value = value === null || value === undefined ? '' : String(value);
      if (opts.min !== undefined) input.min = opts.min;
      if (opts.max !== undefined) input.max = opts.max;
      if (opts.step !== undefined) input.step = opts.step;
      if (opts.maxLength) input.maxLength = opts.maxLength;
      if (opts.required) input.required = true;
      input.addEventListener('input', () => {
        const row = book.streams[index];
        row[field] = opts.percent ? fromPct(input.value) :
          opts.number ? (input.value.trim() === '' ? '' : Number(input.value)) : input.value;
        tr.classList.add('rc-row-dirty');
        showError('');
        status();
        // The server remains the only source of canonical validation.
        const indicator = tr.querySelector('.rc-row-status');
        if (indicator) { indicator.textContent = 'Not validated'; indicator.dataset.state = 'ok'; }
      });
      return input;
    }
    function render() {
      tbody.replaceChildren();
      empty.hidden = book.streams.length > 0;
      book.streams.forEach((row, index) => {
        const kind = kindOverrides.get(row) || displayKind(row);
        const tr = document.createElement('tr');
        tr.dataset.revenueRow = String(index);
        const id = entry(tr, index, 'id', row.id, {required:true, maxLength:200, label:'Contract ID'});
        setCell(tr, 'Contract ID', id);
        const select = document.createElement('select');
        select.dataset.field = 'kind';
        select.setAttribute('aria-label', 'Revenue stream type');
        for (const [key, title] of KINDS) {
          const option = document.createElement('option');
          option.value = key; option.textContent = title;
          if (key === kind) option.selected = true;
          select.appendChild(option);
        }
        select.addEventListener('change', () => {
          const next = select.value;
          const old = book.streams[index];
          if (next === kind) return;
          if (!window.confirm('Change contract type? Type-specific terms will be cleared. Save remains manual.')) {
            select.value = kind; return;
          }
          const changed = {...old};
          if (isScheduled(next)) {
            book.version = 2;
            changed.type = next === 'scheduled_ppa' ? 'ppa' : 'merchant';
            changed.indexation_rate = 0;
            changed.price_curve = Array.isArray(old.price_curve) ? old.price_curve : [];
            if (next === 'scheduled_ppa') { delete changed.capture_rate; }
            delete changed.reference_stream_id;
            if (changed.volume_share === null && next === 'scheduled_ppa') changed.volume_share = 0;
          } else if (isMerchant(next)) {
            changed.type = 'merchant';
            changed.volume_share = next === 'residual_merchant' ? null :
              (typeof old.volume_share === 'number' ? old.volume_share : 0);
            delete changed.reference_stream_id;
          } else if (next === 'cfd') {
            changed.type = 'cfd';
            changed.volume_share = typeof old.volume_share === 'number' ? old.volume_share : 0;
            changed.indexation_rate = 0;
            changed.reference_stream_id = old.reference_stream_id || '';
            delete changed.capture_rate;
          } else {
            changed.type = 'ppa';
            changed.volume_share = typeof old.volume_share === 'number' ? old.volume_share : 0;
            changed.indexation_rate = next === 'fixed_ppa' ? 0 : old.indexation_rate;
            delete changed.capture_rate;
            delete changed.reference_stream_id;
          }
          if (!isScheduled(next)) delete changed.price_curve;
          book.streams[index] = changed;
          kindOverrides.set(changed, next);
          showError('');
          if (next === 'cfd' || isMerchant(next)) advancedMode(true);
          render(); status();
        });
        setCell(tr, 'Revenue stream type', select);
        setCell(tr, 'Start date', entry(tr,index,'start_date',row.start_date,
          {type:'date',required:true,label:'Contract start date'}));
        setCell(tr, 'End date', entry(tr,index,'end_date',row.end_date,
          {type:'date',required:true,label:'Contract end date, exclusive'}));
        setCell(tr, 'Allocation', kind === 'residual_merchant' ?
          document.createTextNode('Residual') :
          entry(tr,index,'volume_share',toPct(row.volume_share),
            {type:'number',number:true,percent:true,min:0,max:100,step:'any',label:'Generation allocation percent'}));
        // An explicit price_curve is the SOLE economic price authority for
        // scheduled PPA/Merchant. Keep the legacy scalar in canonical JSON for
        // backward-compatible validation/serialization, but NEVER expose it
        // as an editable or apparently effective scheduled contract price.
        if (isScheduled(kind)) {
          const indicator = document.createElement('span');
          indicator.textContent = 'Curve prices only';
          indicator.dataset.revenueCurveAuthority = 'true';
          indicator.title = 'Effective EUR/MWh comes exclusively from dated price points below. ' +
            'The legacy flat-price field is retained in serialized JSON for compatibility, ' +
            'but is ignored while a price curve is active.';
          setCell(tr, 'Price EUR/MWh · curve only', indicator);
        } else {
          setCell(tr, 'Price EUR/MWh', entry(tr,index,'price_eur_mwh',row.price_eur_mwh,
            {type:'number',number:true,min:0,step:'any',label:'Contract price EUR per MWh'}),
            kind !== 'cfd');
        }
        setCell(tr, 'Index %', entry(tr,index,'indexation_rate',toPct(row.indexation_rate),
          {type:'number',number:true,percent:true,min:0,max:100,step:'any',label:'Annual indexation percent'}),
          kind === 'indexed_ppa' || (isMerchant(kind) && !isScheduled(kind)));
        const curveCell = document.createElement('button');
        curveCell.type = 'button';
        curveCell.textContent = 'Edit points (' + (row.price_curve?.length || 0) + ')';
        curveCell.setAttribute('aria-label', 'Edit price points for ' + (row.id || 'new contract'));
        curveCell.addEventListener('click', () => {
          const details = tr.nextElementSibling?.querySelector('.rc-curve-editor');
          if (details) { details.open = !details.open; if (details.open) details.scrollIntoView({block:'nearest'}); }
        });
        setCell(tr, 'Price schedule', curveCell, isScheduled(kind));
        setCell(tr, 'CfD strike', entry(tr,index,'price_eur_mwh',row.price_eur_mwh,
          {type:'number',number:true,min:0,step:'any',label:'CfD strike EUR per MWh'}),kind === 'cfd');
        setCell(tr, 'Capture %', entry(tr,index,'capture_rate',toPct(row.capture_rate === undefined ? 1 : row.capture_rate),
          {type:'number',number:true,percent:true,min:0,max:100,step:'any',label:'Merchant capture percent'}),
          isMerchant(kind),true);
        setCell(tr, 'CfD reference', entry(tr,index,'reference_stream_id',row.reference_stream_id || '',
          {label:'Referenced merchant contract ID'}),kind === 'cfd',true);
        setCell(tr, 'Source reference', entry(tr,index,'source_ref',row.source_ref,
          {maxLength:200,required:true,label:'Declared source reference'}),true,true);
        const state = document.createElement('span');
        state.className = 'rc-row-status';
        state.textContent = 'Pending server validation'; state.dataset.state = 'ok';
        setCell(tr, 'Validation', state);
        const remove = document.createElement('button');
        remove.type = 'button'; remove.textContent = 'Remove'; remove.className = 'rc-remove';
        remove.setAttribute('aria-label','Remove contract ' + (row.id || String(index + 1)));
        remove.addEventListener('click', () => {
          if (!window.confirm('Remove this contract from the draft? Changes apply only after Save.')) return;
          book.streams.splice(index,1);
          showError(''); render(); status();
        });
        setCell(tr,'Remove',remove);
        tbody.appendChild(tr);
        if (isScheduled(kind)) {
          const extra = document.createElement('tr');
          extra.className = 'rc-price-curve-row';
          const td = document.createElement('td');
          td.colSpan = 14;
          const details = document.createElement('details');
          details.className = 'rc-curve-editor';
          const summary = document.createElement('summary');
          summary.textContent = 'Exact operating-period prices · ' + (row.id || 'new contract') +
            ' · source: ' + (row.source_ref || 'required');
          details.appendChild(summary);
          const note = document.createElement('p');
          note.className = 'd-context';
          note.textContent = 'Explicit nominal EUR/MWh at every active operating period start. No indexation, interpolation, hold-last or extrapolation.';
          details.appendChild(note);
          const points = document.createElement('div');
          points.className = 'rc-curve-points';
          function writePoint(point, at) {
            const line = document.createElement('div');
            line.className = 'rc-curve-point';
            const day = document.createElement('input'); day.type = 'date';
            day.value = point.period_start || ''; day.setAttribute('aria-label','Operating period start');
            const price = document.createElement('input'); price.type = 'number';
            price.min = '0'; price.step = 'any';
            price.value = point.price_eur_mwh ?? '';
            price.setAttribute('aria-label','Nominal EUR/MWh');
            const remove = document.createElement('button'); remove.type = 'button';
            remove.textContent = 'Remove point';
            day.addEventListener('input', () => { point.period_start = day.value; showError(''); status(); });
            price.addEventListener('input', () => {
              point.price_eur_mwh = price.value.trim() === '' ? '' : Number(price.value);
              showError(''); status();
            });
            remove.addEventListener('click', () => {
              row.price_curve.splice(row.price_curve.indexOf(point), 1);
              line.remove(); showError(''); status();
            });
            line.append(day, price, remove);
            points.appendChild(line);
          }
          row.price_curve.forEach(writePoint);
          const add = document.createElement('button'); add.type = 'button';
          add.textContent = '+ Price point';
          add.addEventListener('click', () => {
            if (row.price_curve.length >= 600) { showError('Maximum 600 price points.'); return; }
            const point = {period_start:'', price_eur_mwh:''};
            row.price_curve.push(point);
            writePoint(point); status();
          });
          const paste = document.createElement('textarea');
          paste.rows = 3;
          paste.placeholder = '2031-01-01\t82.50\n2031-07-01\t79.00';
          paste.setAttribute('aria-label','Paste dated price points (date TAB price, one per line)');
          const importBtn = document.createElement('button'); importBtn.type = 'button';
          importBtn.textContent = 'Replace curve with pasted points';
          importBtn.addEventListener('click', () => {
            try {
              const lines = paste.value.trim().split(/\r?\n/).filter(Boolean);
              if (!lines.length || lines.length > 600) throw Error('Supply 1–600 dated price rows.');
              const newPoints = lines.map(line => {
                const fields = line.split(/[\t,;]/).map(v => v.trim());
                if (fields.length !== 2 || !/^\d{4}-\d{2}-\d{2}$/.test(fields[0]) ||
                    !fields[1] || !Number.isFinite(Number(fields[1])) || Number(fields[1]) < 0)
                  throw Error('Each row must contain an ISO date and a finite nonnegative EUR/MWh price.');
                return {period_start:fields[0], price_eur_mwh:Number(fields[1])};
              });
              for (let j=1; j<newPoints.length; j++)
                if (newPoints[j].period_start <= newPoints[j-1].period_start)
                  throw Error('Curve dates must be strictly increasing and unique.');
              row.price_curve = newPoints;
              showError(''); render(); status();
            } catch(err) { showError(err.message); }
          });
          details.append(points, add, paste, importBtn);
          td.appendChild(details);
          extra.appendChild(td);
          tbody.appendChild(extra);
        }
      });
    }
    function validate() {
      if (book.streams.length > 24) return 'At most 24 contracts are supported.';
      if (!book.streams.length) return '';  // Empty payload explicitly restores legacy pricing.
      const seen = new Set();
      for (const [index,row] of book.streams.entries()) {
        const n = index + 1;
        if (!row.id || !row.id.trim() || row.id.length > 200 || seen.has(row.id))
          return 'Row ' + n + ': contract ID is required and must be unique.';
        seen.add(row.id);
        if (!row.source_ref || !row.source_ref.trim() || row.source_ref.length > 200) {
          advancedMode(true);
          return 'Row ' + n + ': a source reference is required.';
        }
        const realDate = s => typeof s === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(s) &&
          Number.isFinite(Date.parse(s)) && new Date(s + 'T00:00:00Z').toISOString().slice(0,10) === s;
        if (!realDate(row.start_date) || !realDate(row.end_date) || row.end_date <= row.start_date)
          return 'Row ' + n + ': supply valid dates (end exclusive, after start).';
        for (const key of ['price_eur_mwh', 'indexation_rate', 'volume_share']) {
          if (key === 'volume_share' && row.type === 'merchant' && row.volume_share === null) continue;
          const value = row[key];
          if (typeof value !== 'number' || !Number.isFinite(value) || value < 0 ||
              (key !== 'price_eur_mwh' && value > 1))
            return 'Row ' + n + ': invalid ' + key + '. Values must be finite and nonnegative.';
        }
        if (row.type === 'merchant' && 'capture_rate' in row &&
            (typeof row.capture_rate !== 'number' || !Number.isFinite(row.capture_rate) ||
             row.capture_rate < 0 || row.capture_rate > 1))
          return 'Row ' + n + ': merchant capture must be between 0 and 100%.';
        if (row.type === 'cfd' && (row.indexation_rate !== 0 || !row.reference_stream_id ||
             !book.streams.some(s => s.type === 'merchant' && s.id === row.reference_stream_id))) {
          advancedMode(true);
          return 'Row ' + n + ': CfD requires a valid Merchant reference and a non-indexed strike.';
        }
        if (Array.isArray(row.price_curve)) {
          if (row.type === 'cfd' || book.version !== 2 || row.indexation_rate !== 0 ||
              row.price_curve.length < 1 || row.price_curve.length > 600)
            return 'Row ' + n + ': scheduled prices require V2 and zero indexation.';
          let last = '';
          for (const point of row.price_curve) {
            if (!realDate(point.period_start) ||
                point.period_start < row.start_date || point.period_start >= row.end_date ||
                point.period_start <= last || typeof point.price_eur_mwh !== 'number' ||
                !Number.isFinite(point.price_eur_mwh) || point.price_eur_mwh < 0)
              return 'Row ' + n + ': curve points must be strictly ordered, dated inside contract tenor and nonnegative.';
            last = point.period_start;
          }
          // Server validates one price per actual canonical operating period.
        }
        if (kindOverrides.get(row) === 'indexed_ppa' && !(row.indexation_rate > 0))
          return 'Row ' + n + ': indexed PPA requires a positive annual indexation rate.';
      }
      return '';
    }
    try {
      book = safeBook(raw, form.dataset.technology);
    } catch (exc) {
      blocked = true;
      book = {streams:[]};
      showError(exc.message || 'Unsafe existing contract configuration. Editing blocked.');
      form.querySelector('[data-revenue-add]').disabled = true;
      advancedBtn.disabled = true;
      save.disabled = true;
      return;
    }
    baseline = JSON.stringify(book);
    form.querySelector('[data-revenue-add]').addEventListener('click', () => {
      if (book.streams.length >= 24) { showError('At most 24 contracts are supported.'); return; }
      const kind = form.querySelector('[data-revenue-add-type]').value;
      const added = newRow(kind);
      if (isScheduled(kind)) book.version = 2;
      book.streams.push(added);
      kindOverrides.set(added, kind);
      advancedMode(true); showError(''); render(); status();
      const last = tbody.lastElementChild;
      last?.querySelector('[data-field=id]')?.focus();
    });
    advancedBtn.addEventListener('click', () => advancedMode(!advanced));
    tbody.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && (event.target.matches('input, select'))) {
        event.preventDefault();
        event.target.blur(); // Commits the cell to local draft; Save is explicit.
        feedback.textContent = 'Cell committed to draft · Save contracts to persist.';
      } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        const field = event.target.dataset.field;
        if (!field) return;
        const current = event.target.closest('tr');
        const next = event.key === 'ArrowDown' ? current?.nextElementSibling : current?.previousElementSibling;
        const target = [...(next?.querySelectorAll('[data-field]') || [])].find(el =>
          el.dataset.field === field && !el.closest('[hidden]'));
        if (target) { event.preventDefault(); target.focus(); if (target.select) target.select(); }
      }
    });
    form.addEventListener('submit', event => {
      if (event.submitter?.value === 'inherit') return;
      const problem = validate();
      if (problem) {
        event.preventDefault(); event.stopImmediatePropagation();
        showError(problem); error.scrollIntoView({block:'nearest'}); return;
      }
      payload.value = book.streams.length ? JSON.stringify(book) : '';
    }, true);
    form.addEventListener('htmx:configRequest', event => {
      if (event.detail.elt !== form) return;
      if (event.detail.parameters.action === 'inherit') return;
      const problem = validate();
      if (problem) { event.preventDefault(); showError(problem); return; }
      payload.value = book.streams.length ? JSON.stringify(book) : '';
      event.detail.parameters.contracts = payload.value;
    });
    form.addEventListener('htmx:responseError', event => {
      let message = 'Save failed. Working Copy was not changed; check the inputs and reload if the scenario moved.';
      try { message = JSON.parse(event.detail.xhr.responseText).error || message; } catch (_) {}
      showError(message);
    });
    advancedMode(false);
    render();
    status();
  }

  function scan() {
    document.querySelectorAll('form[data-revenue-editor]').forEach(begin);
  }
  document.addEventListener('DOMContentLoaded', scan);
  document.addEventListener('htmx:afterSwap', scan);
  document.addEventListener('htmx:afterSettle', scan);
  // Stress has a separate read-only endpoint. Show typed 4xx errors rather than
  // letting HTMX leave the previous, now misleading comparison on screen.
  document.addEventListener('htmx:responseError', event => {
    if (!event.detail.elt?.matches?.('[data-testid="revenue-stress-form"]')) return;
    const result = document.getElementById('revenue-stress-results');
    if (!result) return;
    const parsed = new DOMParser().parseFromString(event.detail.xhr.responseText, 'text/html');
    const message = parsed.querySelector('[role="alert"]')?.textContent?.trim() ||
      'UNAVAILABLE: request rejected; no comparison was saved.';
    result.replaceChildren(document.createTextNode(message));
    result.setAttribute('role', 'alert');
  });
  scan();
})();
