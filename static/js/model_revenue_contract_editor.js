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
  const OPTIONAL_KEYS = ['capture_rate', 'reference_stream_id', 'price_curve', 'index_series', 'indexation_timing', 'price_rounding'];
  const INDEX_KEYS = ['operating_year', 'level', 'basis'];
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
      ? (row.indexation_rate > 0 || Array.isArray(row.index_series) || row.indexation_timing ? 'indexed_ppa' : 'fixed_ppa')
      : row.type === 'merchant'
        ? (row.volume_share === null ? 'residual_merchant' : 'merchant') : 'cfd';

  function safeBook(raw, technology, v3Enabled) {
    if (!['solar', 'wind'].includes(technology)) throw Error('Only Solar and Wind revenue contracts are supported.');
    const book = raw ? JSON.parse(raw) :
      {version: 1, technology, indexation_basis: 'OPERATING_YEAR', streams: []};
    const keys = book.version === 3 ? ROOT_KEYS.concat(['products', 'environmental_rights']) : ROOT_KEYS;
    if (!legalKeys(book, keys) || keys.some(k => !(k in book)) ||
        ![1, 2, 3].includes(book.version) || (book.version === 3 && !v3Enabled) || book.technology !== technology ||
        book.indexation_basis !== 'OPERATING_YEAR' || !Array.isArray(book.streams) ||
        book.streams.length > 24) {
      throw Error('Existing contract configuration cannot be represented safely. No changes have been made.');
    }
    if (book.version === 3 && (!Array.isArray(book.products) || !Array.isArray(book.environmental_rights)))
      throw Error('Invalid non-energy contract book. Editing blocked.');
    for (const row of book.streams) {
      if (!legalKeys(row, BASE_KEYS.concat(OPTIONAL_KEYS)) ||
          BASE_KEYS.some(k => !(k in row)) || !['ppa', 'merchant', 'cfd'].includes(row.type) ||
          row.settlement !== 'SAME_PERIOD' ||
          (row.type !== 'merchant' && 'capture_rate' in row) ||
          (row.type !== 'cfd' && 'reference_stream_id' in row) ||
          ('price_curve' in row && (![2, 3].includes(book.version) || row.type === 'cfd' ||
            !Array.isArray(row.price_curve) || row.indexation_rate !== 0 ||
            row.price_curve.length > 600 || row.price_curve.some(point =>
              !legalKeys(point, ['period_start', 'price_eur_mwh']) ||
              !('period_start' in point) || !('price_eur_mwh' in point)))) ||
          ('index_series' in row && (![2, 3].includes(book.version) || row.type !== 'ppa' || row.indexation_rate !== 0 ||
            'price_curve' in row || !Array.isArray(row.index_series) || row.index_series.length > 60 ||
            row.index_series.some(point => !legalKeys(point, INDEX_KEYS) || INDEX_KEYS.some(k => !(k in point))))) ||
          ('indexation_timing' in row && (book.version !== 2 || row.type !== 'ppa' || 'price_curve' in row || 'index_series' in row ||
            !legalKeys(row.indexation_timing, ['method','price_base_date','start_rule','resolved_start_date','first_review_date',
              'review_frequency','mid_period_policy','signing_date','custom_start_date','index_base_date','observations','reviews'])))) {
        throw Error('An existing stream contains unsupported terms. Editing is blocked to preserve it.');
      }
      if ('price_rounding' in row) {
        const p = row.price_rounding;
        if (book.version !== 2 || row.type !== 'ppa' ||
            !legalKeys(p, ['enabled', 'decimal_places', 'method']) || typeof p.enabled !== 'boolean' ||
            ('decimal_places' in p && ![2, 3, 4, 6].includes(p.decimal_places)) ||
            ('method' in p && !['HALF_UP', 'HALF_EVEN'].includes(p.method)) ||
            (p.enabled && (!('decimal_places' in p) || !('method' in p) ||
              row.price_curve || !(row.indexation_rate > 0 || row.index_series || row.indexation_timing)))) {
          throw Error('Unsupported contractual price rounding terms. No changes have been made.');
        }
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
    function revealInvalid(input) {
      if (!input || !input.willValidate) return;
      const row = input.closest('[data-revenue-row]');
      if (input.closest('[data-revenue-advanced-cell]')) advancedMode(true);
      for (let parent = input.parentElement; parent && parent !== form; parent = parent.parentElement) {
        if (parent.tagName === 'DETAILS') parent.open = true;
      }
      form.querySelectorAll('[data-field-error]').forEach(el => el.remove());
      form.querySelectorAll('[data-revenue-invalid]').forEach(el => {
        el.removeAttribute('aria-invalid'); el.removeAttribute('data-revenue-invalid');
        if (el.getAttribute('aria-describedby') === 'rc-invalid-field') el.removeAttribute('aria-describedby');
      });
      const index = row ? Number(row.dataset.revenueRow) : null;
      const contract = index === null ? 'Contract' : 'Contract ' + (book.streams[index]?.id || '(unnamed)') + ' (row ' + (index + 1) + ')';
      const message = contract + ' · ' + (input.getAttribute('aria-label') || input.name || 'Field') + ': ' + input.validationMessage;
      const note = document.createElement('span');
      note.dataset.fieldError = ''; note.className = 'rc-field-error'; note.setAttribute('role', 'alert');
      note.id = 'rc-invalid-field'; note.textContent = message;
      input.after(note); input.setAttribute('aria-invalid', 'true'); input.setAttribute('data-revenue-invalid', '');
      input.setAttribute('aria-describedby', note.id);
      showError(message);
      input.focus({preventScroll:true});
      input.scrollIntoView({block:'center', inline:'center'});
    }
    // Native validation runs before submit (including HTMX); hidden advanced cells must not fail silently.
    form.addEventListener('invalid', event => {
      event.preventDefault();
      if (event.target === [...form.elements].find(el => el.willValidate && !el.validity.valid)) revealInvalid(event.target);
    }, true);
    form.addEventListener('input', event => {
      const input = event.target;
      if (!input.hasAttribute('data-revenue-invalid')) return;
      input.removeAttribute('aria-invalid'); input.removeAttribute('data-revenue-invalid');
      if (input.getAttribute('aria-describedby') === 'rc-invalid-field') input.removeAttribute('aria-describedby');
      form.querySelector('[data-field-error]')?.remove();
    });
    // PPA-01 explicit CPI/PPI index series. Presentation/serialization only: levels are typed or pasted by the user, never invented; the canonical
    // Python validator and runtime remain the only authority for what is accepted and what a Run prices.
    const operatingYears = (() => { try { return JSON.parse(form.querySelector('[data-revenue-quick]')?.dataset.operatingYears || '[]'); } catch (_) { return []; } })();
    const LEVEL = /^\d+(\.\d+)?$/;
    const contractYears = (row) => {
      if (!row.start_date || !row.end_date) return [];
      return operatingYears.filter(y => y.period_starts.some(d => d >= row.start_date && d < row.end_date)).map(y => y.year);
    };
    const yearSpan = (year) => { const y = operatingYears.find(e => e.year === year); return y ? y.start + ' → ' + y.end : ''; };
    const levelOf = (point) => (typeof point.level === 'number' && Number.isFinite(point.level) && point.level > 0) ? point.level : null;
    function effectivePrice(row, point) {            // read-only preview of price x level / base level; the Run decides the committed price
      if (row.price_rounding?.enabled) return 'See saved period prices';
      const base = row.index_series.length ? levelOf(row.index_series[0]) : null, level = levelOf(point);
      if (base === null || level === null || typeof row.price_eur_mwh !== 'number' || !Number.isFinite(row.price_eur_mwh)) return '—';
      return (row.price_eur_mwh * level / base).toFixed(4);
    }
    // Strict paste: one level per line (aligned to the base year) or year / level [/ OBSERVED|FORECAST]. Anything else is rejected, never guessed.
    function parseIndexPaste(text, baseYear, fallbackLength) {
      const lines = text.trim().split(/\r?\n/).map(l => l.trim()).filter(Boolean);
      if (!lines.length || lines.length > 60) throw Error('Paste 1-60 index rows.');
      const out = [];
      for (const [i, line] of lines.entries()) {
        const cells = line.split(/[\t;]/).map(v => v.trim());
        let year = baseYear + i, levelText, basis = 'FORECAST';
        if (cells.length === 1) levelText = cells[0];
        else if (cells.length >= 2 && cells.length <= 3 && /^\d+$/.test(cells[0])) {
          year = Number(cells[0]); levelText = cells[1];
          if (cells[2] !== undefined) {
            const b = cells[2].toUpperCase();
            if (!['OBSERVED', 'FORECAST'].includes(b)) throw Error('Row ' + (i + 1) + ': basis must be OBSERVED or FORECAST.');
            basis = b;
          }
        } else throw Error('Row ' + (i + 1) + ': use one level per line, or year, level and optionally OBSERVED/FORECAST separated by tabs.');
        if (!LEVEL.test(levelText) || !(Number(levelText) > 0)) throw Error('Row ' + (i + 1) + ': "' + levelText + '" is not an index level above zero (use a dot as the decimal separator).');
        if (out.length && year !== out[out.length - 1].operating_year + 1) throw Error('Row ' + (i + 1) + ': operating years must be consecutive; year ' + (out[out.length - 1].operating_year + 1) + ' is missing.');
        out.push({operating_year: year, level: Number(levelText), basis});
      }
      return out;
    }
    function seriesProblem(row, label) {
      const series = row.index_series;
      if (!Array.isArray(series) || !series.length || series.length > 60) return label + ': enter 1-60 index observations.';
      let previous = null;
      for (const point of series) {
        if (!Number.isInteger(point.operating_year) || point.operating_year < 1) return label + ': each observation needs an operating year from 1.';
        if (previous !== null && point.operating_year !== previous + 1) return label + ': operating year ' + (previous + 1) + ' has no index level; the series must be continuous (no interpolation or fallback rate).';
        previous = point.operating_year;
        if (levelOf(point) === null) return label + ': enter a published index level above zero for operating year ' + point.operating_year + '.';
        if (!['OBSERVED', 'FORECAST'].includes(point.basis)) return label + ': mark operating year ' + point.operating_year + ' as observed or forecast.';
      }
      const years = contractYears(row);
      if (years.length) {
        if (series[0].operating_year > years[0]) return label + ': the base index (year ' + series[0].operating_year + ') must be at or before the first priced operating year ' + years[0] + '.';
        const last = series[series.length - 1].operating_year;
        if (last < years[years.length - 1]) return label + ': no index level for operating year ' + (last + 1) + (last + 1 < years[years.length - 1] ? '–' + years[years.length - 1] : '') + '; levels are never extrapolated or replaced by an annual rate.';
      }
      return '';
    }
    function seriesIssue() {
      for (const row of book.streams) {
        if (!Array.isArray(row.index_series)) continue;
        const problem = seriesProblem(row, row.id || 'An indexed PPA');
        if (problem) return problem;
      }
      return '';
    }
    function curveIssue(axis) {
      for (const row of book.streams) {
        if (!Array.isArray(row.price_curve)) continue;
        const label = row.id || 'a Scheduled contract';
        if (!row.price_curve.length) return label + ' has no price points.';
        const required = axis.filter(d => d >= row.start_date && d < row.end_date);
        const seen = new Set();
        for (const pt of row.price_curve) {
          if (!pt.period_start) return label + ' has a price point without a date.';
          if (seen.has(pt.period_start)) return label + ' repeats the period ' + pt.period_start + '.';
          seen.add(pt.period_start);
          if (axis.length && !required.includes(pt.period_start)) return label + ': ' + pt.period_start + ' is not an operating period inside the contract.';
          if (typeof pt.price_eur_mwh !== 'number' || !Number.isFinite(pt.price_eur_mwh) || pt.price_eur_mwh < 0)
            return label + ': the price for ' + pt.period_start + ' must be a number of zero or more.';
        }
        const missing = required.filter(d => !seen.has(d));
        if (missing.length) return label + ' is missing ' + missing.length + ' operating period' + (missing.length === 1 ? '' : 's') + ' (first: ' + missing[0] + ').';
        const dates = row.price_curve.map(pt => pt.period_start);
        if (dates.some((d, i) => i && d <= dates[i - 1])) return label + ': price points must be in date order.';
      }
      return '';
    }
    // Contracted / residual / unallocated production, computed per contract-date segment exactly like the canonical validator (explicit shares only).
    function allocationSummary() {
      const box = form.querySelector('[data-revenue-allocation]');
      if (!box) return;
      const rows = book.streams.filter(r => r.start_date && r.end_date);
      if (!rows.length) { box.textContent = ''; return; }
      const cuts = Array.from(new Set(rows.flatMap(r => [r.start_date, r.end_date]))).sort();
      let peak = 0, peakAt = '', residual = rows.some(r => r.type === 'merchant' && r.volume_share === null);
      for (let i = 0; i < cuts.length - 1; i += 1) {
        const total = rows.filter(r => typeof r.volume_share === 'number' && r.start_date <= cuts[i] && cuts[i] < r.end_date).reduce((a, r) => a + r.volume_share, 0);
        if (total > peak + 1e-12) { peak = total; peakAt = cuts[i]; }
      }
      const pct = (x) => String(Number((x * 100).toPrecision(10))) + '%';
      box.dataset.over = String(peak > 1 + 1e-9);
      box.textContent = peak > 1 + 1e-9
        ? 'Contracted production adds up to ' + pct(peak) + ' from ' + peakAt + ' - it cannot exceed 100%.'
        : 'Contracted production up to ' + pct(peak) + ' · ' + (residual ? 'residual Merchant takes the remainder (price entered on its row)' : 'unallocated up to ' + pct(1 - peak) + ' (add a residual Merchant contract to sell it)');
    }
    function calendarEditor(row) {
      const box = document.createElement('div'); box.dataset.calendarEditor = '';
      const terms = row.indexation_timing;
      const grid = document.createElement('div'); grid.className = 'rc-product-fields';
      const changed = () => { showError(''); status(); };
      const resolve = () => {
        terms.resolved_start_date = terms.start_rule === 'SIGNATURE' ? terms.signing_date || '' :
          terms.start_rule === 'CUSTOM' ? terms.custom_start_date || '' :
          terms.start_rule === 'PPA_START' ? row.start_date : form.querySelector('[data-calendar-cod]').value;
        box.querySelector('[data-calendar-resolved]').textContent = terms.resolved_start_date || 'Date required';
      };
      function field(key, title, options) {
        const label = document.createElement('label'); label.textContent = title;
        const el = document.createElement(options ? 'select' : 'input');
        el.dataset.calendarField = key; el.setAttribute('aria-label', title);
        if (!options) el.type = 'date';
        else options.forEach(([value, text]) => {
          const option = document.createElement('option'); option.value = value; option.textContent = text; el.appendChild(option);
        });
        el.value = terms[key] || '';
        el.addEventListener(options ? 'change' : 'input', () => {
          terms[key] = el.value;
          if (key === 'start_rule') {
            delete terms.signing_date; delete terms.custom_start_date;
            if (el.value === 'SIGNATURE') terms.signing_date = '';
            if (el.value === 'CUSTOM') terms.custom_start_date = '';
          }
          if (key === 'method') {
            if (el.value === 'DATED_INDEX_LEVELS') {
              row.indexation_rate = 0;
              terms.index_base_date = ''; terms.observations = []; terms.reviews = [];
            } else {
              delete terms.index_base_date; delete terms.observations; delete terms.reviews;
            }
          }
          resolve(); changed();
          if (options) { render(); status(); }
        });
        label.appendChild(el); grid.appendChild(label);
      }
      field('method', 'Indexation method', [['ANNUAL_FIXED','Fixed annual rate'], ['DATED_INDEX_LEVELS','Dated CPI/PPI levels']]);
      field('price_base_date', 'Price base date');
      field('start_rule', 'Indexation starts from', [['SIGNATURE','Contract signing date'], ['COD','COD'], ['PPA_START','PPA commencement date'], ['CUSTOM','Custom date']]);
      if (terms.start_rule === 'SIGNATURE') field('signing_date', 'Contract signing date');
      if (terms.start_rule === 'CUSTOM') field('custom_start_date', 'Custom indexation date');
      field('first_review_date', 'First effective price review');
      if (terms.method === 'DATED_INDEX_LEVELS') field('index_base_date', 'Base index reference date');
      box.appendChild(grid);
      const dates = document.createElement('p');
      dates.append('Effective indexation start: ');
      const resolved = document.createElement('output'); resolved.dataset.calendarResolved = '';
      resolved.textContent = terms.resolved_start_date || 'Date required'; dates.append(resolved);
      box.appendChild(dates);
      const projectCod = form.querySelector('[data-calendar-cod]').value;
      if (terms.start_rule === 'COD' && projectCod && terms.resolved_start_date !== projectCod) {
        const rebind = document.createElement('button'); rebind.type = 'button';
        rebind.textContent = 'Use Project Timeline COD: ' + projectCod;
        rebind.addEventListener('click', () => { resolve(); changed(); }); box.appendChild(rebind);
      }
      // Only date selection/serialization happens here. The server resolves financial prices.
      if (terms.method === 'DATED_INDEX_LEVELS') {
        const note = document.createElement('p'); note.textContent = 'Supply the base and every annual review, including reviews before COD. Reference dates and publication dates are distinct.'; box.appendChild(note);
        function records(key, title, columns, blank) {
          const section = document.createElement('details'); section.open = true;
          const heading = document.createElement('summary'); heading.textContent = title; section.appendChild(heading);
          const table = document.createElement('table'); table.className = 'rc-index-table'; table.dataset.calendarTable = key;
          const head = table.createTHead().insertRow();
          columns.forEach(([, label]) => { const th = document.createElement('th'); th.scope = 'col'; th.textContent = label; head.appendChild(th); });
          const body = table.createTBody();
          terms[key].forEach((point, at) => {
            const line = body.insertRow();
            columns.forEach(([name, title, type]) => {
              const cell = line.insertCell();
              const input = document.createElement(type === 'basis' ? 'select' : 'input');
              if (type === 'basis') ['OBSERVED','FORECAST'].forEach(value => { const option = document.createElement('option'); option.value = value; option.textContent = value; input.appendChild(option); });
              else input.type = type || 'text';
              if (type === 'number') input.step = 'any';
              input.value = point[name] == null ? '' : point[name];
              input.setAttribute('aria-label', title + ' row ' + (at+1)); input.dataset.calendarPoint = name;
              input.addEventListener(type === 'basis' ? 'change' : 'input', () => {
                point[name] = type === 'number' ? (input.value === '' ? '' : Number(input.value)) :
                  name === 'publication_date' && input.value === '' ? null : input.value;
                changed();
              });
              cell.appendChild(input);
            });
            const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = 'Remove';
            remove.setAttribute('aria-label','Remove ' + title + ' row ' + (at+1));
            remove.addEventListener('click', () => { terms[key].splice(at,1); render(); status(); }); line.insertCell().appendChild(remove);
          });
          const scroll = document.createElement('div'); scroll.className = 'rc-index-scroll'; scroll.appendChild(table); section.appendChild(scroll);
          const add = document.createElement('button'); add.type = 'button'; add.textContent = 'Add row';
          add.addEventListener('click', () => { terms[key].push({...blank}); render(); status(); }); section.appendChild(add);
          const paste = document.createElement('textarea'); paste.rows = 3;
          paste.setAttribute('aria-label','Paste ' + title); paste.placeholder = columns.map(c => c[1]).join('\t');
          section.appendChild(paste);
          const use = document.createElement('button'); use.type = 'button'; use.textContent = 'Replace with pasted rows';
          use.addEventListener('click', () => {
            const lines = paste.value.trim().split(/\r?\n/);
            if (!paste.value.trim() || lines.length > 601) { showError('Paste explicit rows, at most 601.'); return; }
            const parsed = [];
            for (const line of lines) {
              const cells = line.split('\t');
              if (cells.length !== columns.length) { showError('Use tab-separated columns: ' + columns.map(c => c[1]).join(', ')); return; }
              const record = {};
              for (let i=0; i<columns.length; i++) {
                const [name,,type] = columns[i]; const text = cells[i].trim();
                if (type === 'number' && (!LEVEL.test(text) || !(Number(text)>0))) { showError('Every index level must be a finite number above zero.'); return; }
                record[name] = type === 'number' ? Number(text) : name === 'publication_date' && !text ? null : text;
              }
              parsed.push(record);
            }
            terms[key] = parsed; showError(''); render(); status();
          });
          section.appendChild(use); box.appendChild(section);
        }
        records('observations', 'Index observations', [['reference_date','Reference date','date'],['level','Level','number'],['basis','Basis','basis'],['publication_date','Publication date','date'],['source_ref','Source reference','text']],
          {reference_date:'',level:'',basis:'FORECAST',publication_date:null,source_ref:''});
        records('reviews', 'Price reviews', [['effective_date','Effective review','date'],['reference_date','Index reference date','date']], {effective_date:'',reference_date:''});
      }
      const preview = document.createElement('details');
      const title = document.createElement('summary'); title.textContent = 'Period prices (saved contracts)'; preview.appendChild(title);
      const pending = document.createElement('p'); pending.dataset.calendarRefresh = ''; pending.textContent = 'Save contracts to refresh the price preview.'; preview.appendChild(pending);
      const prices = document.createElement('table'); prices.className = 'rc-index-table'; prices.dataset.calendarPrices = '';
      const header = prices.createTHead().insertRow();
      ['Period start','Period end','Price EUR/MWh'].forEach(text => { const th = document.createElement('th'); th.textContent = text; header.appendChild(th); });
      const priceBody = prices.createTBody();
      const saved = JSON.parse(form.querySelector('[data-calendar-preview]').value || '{}');
      (saved[row.id] || []).forEach(p => {
        const line = priceBody.insertRow(); [p.start,p.end,p.price.toFixed(4)].forEach(value => { line.insertCell().textContent = value; });
      });
      const wrap = document.createElement('div'); wrap.className = 'rc-index-scroll rc-calendar-prices-scroll'; wrap.appendChild(prices); preview.appendChild(wrap); box.appendChild(preview);
      return box;
    }
    function roundingEditor(row) {
      const box = document.createElement('details'); box.className = 'rc-rounding-editor';
      const summary = document.createElement('summary'); summary.textContent = 'Contractual Price Rounding'; box.appendChild(summary);
      const toggleLabel = document.createElement('label');
      const toggle = document.createElement('input'); toggle.type = 'checkbox'; toggle.dataset.roundingEnabled = '';
      toggle.checked = row.price_rounding?.enabled === true; toggle.disabled = book.version === 3;
      toggleLabel.append(toggle, document.createTextNode(' Apply contractual price rounding'));
      const controls = document.createElement('div'); controls.className = 'rc-index-modes'; controls.hidden = !toggle.checked;
      const selects = {};
      for (const [key, title, values] of [['decimal_places', 'Decimal places', [2, 3, 4, 6]],
        ['method', 'Rounding method', ['HALF_UP', 'HALF_EVEN']]]) {
        const label = document.createElement('label'); label.textContent = title;
        const select = document.createElement('select'); select.setAttribute('aria-label', title); selects[key] = select;
        values.forEach(value => { const option = document.createElement('option'); option.value = value; option.textContent = value;
          option.selected = value === (row.price_rounding?.[key] ?? (key === 'decimal_places' ? 2 : 'HALF_UP')); select.appendChild(option); });
        select.addEventListener('change', () => { row.price_rounding[key] = key === 'decimal_places' ? Number(select.value) : select.value; status(); });
        label.appendChild(select); controls.appendChild(label);
      }
      toggle.addEventListener('change', () => {
        if (book.version !== 3) book.version = 2;
        row.price_rounding = {enabled: toggle.checked, decimal_places: Number(selects.decimal_places.value), method: selects.method.value};
        controls.hidden = !toggle.checked;
        const outputs = box.closest('tr').querySelectorAll('[data-index-effective]');
        outputs.forEach((out, i) => { out.textContent = effectivePrice(row, row.index_series[i]); });
        showError(''); status();
      });
      const note = document.createElement('p'); note.className = 'd-context'; note.textContent = 'This setting changes calculated PPA revenue.';
      box.append(toggleLabel, controls, note);
      const refresh = document.createElement('p'); refresh.dataset.roundingRefresh = ''; refresh.hidden = true;
      refresh.textContent = 'Save contracts to refresh period prices.'; box.appendChild(refresh);
      const preview = document.createElement('details'); preview.dataset.roundingPrices = '';
      const heading = document.createElement('summary'); heading.textContent = 'Contractual rounding prices (saved contracts)'; preview.appendChild(heading);
      const table = document.createElement('table'); table.className = 'rc-index-table';
      table.innerHTML = '<thead><tr><th>Period</th><th>Base price</th><th>Indexed price</th><th>After floor/cap</th><th>Rounding</th><th>Effective price (EUR/MWh)</th></tr></thead>';
      const body = table.createTBody();
      const saved = JSON.parse(form.querySelector('[data-rounding-preview]')?.value || '{}');
      (saved[row.id] || []).forEach(p => {
        const line = body.insertRow();
        [p.start + ' / ' + p.end, p.base_price, p.indexed_price, p.price_after_floor_cap,
          p.rounding_applied ? p.method + ' / ' + p.decimal_places : 'Not applied before first review', p.effective_price]
          .forEach(value => { line.insertCell().textContent = String(value); });
      });
      const wrap = document.createElement('div'); wrap.className = 'rc-index-scroll rc-calendar-prices-scroll'; wrap.appendChild(table);
      preview.appendChild(wrap); box.appendChild(preview);
      return box;
    }
    function status() {
      dirty = JSON.stringify(book) !== baseline;
      form.dataset.dirty = String(dirty);
      feedback.dataset.dirty = String(dirty);
      feedback.textContent = dirty ? 'Unsaved changes · Save contracts to update Working Copy (Run separately)' :
        'Saved Working Copy · No changes';
      // A Scheduled contract must carry exactly one valid, non-negative price for EVERY operating period inside its dates (no interpolation,
      // no hold-last, nothing inferred for a point the user removed). Anything else is an incomplete draft and cannot be saved.
      const axis = (() => { try { return JSON.parse(form.querySelector('[data-revenue-quick]')?.dataset.periodStarts || '[]'); } catch (_) { return []; } })();
      const issue = curveIssue(axis) || seriesIssue();
      const incomplete = !!issue;
      form.dataset.incomplete = String(incomplete);
      if (dirty && incomplete) feedback.textContent = 'Incomplete draft · ' + issue;
      allocationSummary();
      const over = form.querySelector('[data-revenue-allocation]')?.dataset.over === 'true';
      if (dirty && over && !incomplete) feedback.textContent = 'Not saveable · ' + form.querySelector('[data-revenue-allocation]').textContent;
      save.disabled = !dirty || blocked || incomplete || over;
      form.querySelectorAll('[data-calendar-prices], [data-rounding-prices]').forEach(el => { el.hidden = dirty; });
      form.querySelectorAll('[data-calendar-refresh], [data-rounding-refresh]').forEach(el => { el.hidden = !dirty; });
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
        if (field === 'start_date' && row.indexation_timing?.start_rule === 'PPA_START') {
          row.indexation_timing.resolved_start_date = row.start_date;
          const out = tr.nextElementSibling?.querySelector('[data-calendar-resolved]');
          if (out) out.textContent = row.start_date || 'Date required';
        }
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
            if (book.version !== 3) book.version = 2;
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
          if (next !== 'indexed_ppa') { delete changed.index_series; delete changed.indexation_timing; delete changed.price_rounding; }
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
        if (row.indexation_timing?.method === 'DATED_INDEX_LEVELS') {
          setCell(tr, 'Index %', document.createTextNode('Dated CPI/PPI'));
        } else if (Array.isArray(row.index_series)) {
          const tag = document.createElement('span');
          tag.textContent = 'Index series (' + row.index_series.length + ')';
          tag.dataset.revenueIndexSeriesTag = 'true';
          tag.title = 'Priced from explicit CPI/PPI index levels; no annual percentage applies.';
          setCell(tr, 'Index %', tag);
        } else {
          setCell(tr, 'Index %', entry(tr,index,'indexation_rate',toPct(row.indexation_rate),
            {type:'number',number:true,percent:true,min:0,max:100,step:'any',label:'Annual indexation percent'}),
            kind === 'indexed_ppa' || (isMerchant(kind) && !isScheduled(kind)));
        }
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
        if (kind === 'indexed_ppa') {
          const extra = document.createElement('tr');
          extra.className = 'rc-index-series-row';
          const td = document.createElement('td');
          td.colSpan = 14;
          const details = document.createElement('details');
          details.className = 'rc-index-editor';
          const hasSeries = Array.isArray(row.index_series);
          const hasCalendar = !!row.indexation_timing;
          details.open = hasCalendar || (hasSeries && !!seriesProblem(row, ''));
          const summary = document.createElement('summary');
          summary.textContent = 'Indexation · ' + (row.id || 'new contract') + ' · ' + (hasCalendar ? 'contractual calendar dates' : hasSeries ? 'explicit CPI/PPI index series' : 'fixed annual escalation');
          details.appendChild(summary);
          const modes = document.createElement('div');
          modes.className = 'rc-index-modes';
          modes.setAttribute('role', 'radiogroup'); modes.setAttribute('aria-label', 'Indexation basis for ' + (row.id || 'new contract'));
          for (const [value, title] of [['rate', 'Fixed annual escalation (%)'], ['series', 'Explicit CPI/PPI index series'], ['calendar', 'Contractual calendar dates']]) {
            const label = document.createElement('label');
            const radio = document.createElement('input'); radio.type = 'radio'; radio.name = 'rc-index-mode-' + index; radio.value = value;
            radio.checked = value === (hasCalendar ? 'calendar' : hasSeries ? 'series' : 'rate');
            if (value === 'calendar' && book.version === 3) radio.disabled = true;
            radio.dataset.indexMode = value;
            radio.addEventListener('change', () => {
              if (!radio.checked) return;
              if (hasCalendar && !window.confirm('Replace the contractual calendar terms? Save remains manual.')) { render(); return; }
              if (value === 'calendar') {
                if (hasSeries && !window.confirm('Replace the model-year index levels with calendar terms?')) { render(); return; }
                delete row.index_series;
                if (book.version !== 3) book.version = 2;
                row.indexation_timing = {method:'ANNUAL_FIXED', price_base_date:'', start_rule:'COD',
                  resolved_start_date:form.querySelector('[data-calendar-cod]').value, first_review_date:'',
                  review_frequency:'ANNUAL', mid_period_policy:'PERIOD_BOUNDARY_ONLY'};
              } else if (value === 'series') {
                const years = contractYears(row);
                if (!years.length) { radio.checked = false; modes.querySelector('[data-index-mode=rate]').checked = true; showError('Enter the contract start and end dates first; the index series needs one level per priced operating year.'); return; }
                if (book.version !== 3) book.version = 2;
                delete row.indexation_timing;
                row.indexation_rate = 0;
                row.index_series = years.map(year => ({operating_year: year, level: '', basis: 'FORECAST'}));
              } else {
                if (hasSeries && row.index_series.some(p => p.level !== '') && !window.confirm('Switch to a fixed annual escalation? The typed index levels will be discarded from the draft.')) { radio.checked = false; modes.querySelector('[data-index-mode=series]').checked = true; return; }
                delete row.index_series;
                delete row.indexation_timing;
                row.indexation_rate = 0;
              }
              kindOverrides.set(row, 'indexed_ppa');          // the contract stays an Indexed PPA: a positive annual rate (or a series) is required
              showError(''); render(); status();
              const editors = tbody.querySelectorAll('.rc-index-series-row .rc-index-editor');
              const at = book.streams.filter(r => (kindOverrides.get(r) || displayKind(r)) === 'indexed_ppa').indexOf(row);
              if (editors[at]) editors[at].open = true;
            });
            label.append(radio, document.createTextNode(' ' + title));
            modes.appendChild(label);
          }
          details.appendChild(modes);
          if (hasCalendar) {
            details.appendChild(calendarEditor(row));
          } else if (!hasSeries) {
            const note = document.createElement('p'); note.className = 'd-context';
            note.textContent = 'The annual escalation percentage in the table applies. Choose the index series to price from published CPI/PPI levels instead.';
            details.appendChild(note);
          } else {
            const note = document.createElement('p'); note.className = 'd-context';
            note.textContent = 'Published index level for each model operating year (year 1 = first operating year from COD). The contract price applies at the first level; every later year is price × level ÷ first level. Mark each level as observed (published) or forecast (your assumption). Nothing is interpolated, extrapolated or replaced by an annual rate.';
            details.appendChild(note);
            const table = document.createElement('table'); table.className = 'rc-index-table';
            table.innerHTML = '<thead><tr><th scope="col">Operating year</th><th scope="col">Model dates</th><th scope="col">Index level</th><th scope="col">Basis</th><th scope="col">Effective price (EUR/MWh, preview)</th><th scope="col"></th></tr></thead>';
            const body = document.createElement('tbody');
            row.index_series.forEach((point, i) => {
              const line = document.createElement('tr'); line.dataset.indexPoint = String(point.operating_year);
              const th = document.createElement('th'); th.scope = 'row'; th.textContent = 'Year ' + point.operating_year + (i === 0 ? ' (base)' : '');
              const dates = document.createElement('td'); dates.textContent = yearSpan(point.operating_year);
              const levelTd = document.createElement('td'); const level = document.createElement('input');
              level.type = 'text'; level.inputMode = 'decimal'; level.autocomplete = 'off'; level.dataset.indexLevel = '';
              level.setAttribute('aria-label', 'Index level for operating year ' + point.operating_year);
              level.value = point.level === '' ? '' : String(point.level);
              const priceTd = document.createElement('td'); const out = document.createElement('output'); out.dataset.indexEffective = '';
              out.textContent = effectivePrice(row, point);
              const refreshPrices = () => body.querySelectorAll('tr').forEach((tr, at) => { tr.querySelector('output').textContent = effectivePrice(row, row.index_series[at]); });
              level.addEventListener('input', () => {
                const text = level.value.trim();
                point.level = text === '' ? '' : (LEVEL.test(text) ? Number(text) : NaN);
                level.setAttribute('aria-invalid', String(text !== '' && !LEVEL.test(text)));
                showError(''); refreshPrices(); status();
              });
              levelTd.appendChild(level);
              const basisTd = document.createElement('td'); const basis = document.createElement('select'); basis.dataset.indexBasis = '';
              basis.setAttribute('aria-label', 'Basis for operating year ' + point.operating_year);
              for (const [value, title] of [['OBSERVED', 'Observed (published)'], ['FORECAST', 'Forecast (assumption)']]) {
                const option = document.createElement('option'); option.value = value; option.textContent = title; option.selected = point.basis === value; basis.appendChild(option);
              }
              basis.addEventListener('change', () => { point.basis = basis.value; showError(''); status(); });
              basisTd.appendChild(basis);
              priceTd.appendChild(out);
              const actionTd = document.createElement('td');
              if (i === row.index_series.length - 1 && row.index_series.length > 1) {      // only the last year can go: the series stays continuous
                const del = document.createElement('button'); del.type = 'button'; del.textContent = 'Remove year';
                del.setAttribute('aria-label', 'Remove operating year ' + point.operating_year);
                del.addEventListener('click', () => { row.index_series.pop(); showError(''); render(); status(); reopen(); });
                actionTd.appendChild(del);
              }
              line.append(th, dates, levelTd, basisTd, priceTd, actionTd);
              body.appendChild(line);
            });
            table.appendChild(body);
            const wrap = document.createElement('div'); wrap.className = 'rc-index-scroll'; wrap.appendChild(table);
            details.appendChild(wrap);
            function reopen() {
              const editors = tbody.querySelectorAll('.rc-index-series-row .rc-index-editor');
              const at = book.streams.filter(r => (kindOverrides.get(r) || displayKind(r)) === 'indexed_ppa').indexOf(row);
              if (editors[at]) editors[at].open = true;
            }
            const maxYear = operatingYears.length ? operatingYears[operatingYears.length - 1].year : 0;
            const add = document.createElement('button'); add.type = 'button'; add.textContent = '+ Operating year';
            add.addEventListener('click', () => {
              const next = row.index_series[row.index_series.length - 1].operating_year + 1;
              if (row.index_series.length >= 60 || (maxYear && next > maxYear)) { showError('No further model operating year exists.'); return; }
              row.index_series.push({operating_year: next, level: '', basis: 'FORECAST'});
              showError(''); render(); status(); reopen();
            });
            const paste = document.createElement('textarea'); paste.rows = 3;
            paste.placeholder = '100.0\n102.5\n105.1';
            paste.setAttribute('aria-label', 'Paste index levels (one level per line, or year TAB level TAB OBSERVED or FORECAST)');
            const apply = document.createElement('button'); apply.type = 'button'; apply.textContent = 'Replace levels with pasted values';
            apply.addEventListener('click', () => {
              try {
                const parsed = parseIndexPaste(paste.value, row.index_series[0].operating_year, row.index_series.length);
                row.index_series = parsed;
                showError(''); render(); status(); reopen();
              } catch (err) { showError(err.message); }
            });
            details.append(add, paste, apply);
          }
          details.appendChild(roundingEditor(row));
          td.appendChild(details); extra.appendChild(td); tbody.appendChild(extra);
        }
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
            // Once a date is committed, keep the points in date order (presentation only: no value is changed, added or inferred).
            day.addEventListener('change', () => {
              const sorted = row.price_curve.slice().sort((a, b) => (a.period_start || '9999') < (b.period_start || '9999') ? -1 : (a.period_start || '9999') > (b.period_start || '9999') ? 1 : 0);
              if (sorted.some((pt, i) => pt !== row.price_curve[i])) {
                row.price_curve = sorted;
                const at = book.streams.indexOf(row);
                render(); status();
                const editors = tbody.querySelectorAll('.rc-price-curve-row details');
                if (editors[at]) editors[at].open = true;
              }
            });
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
      renderProducts();
    }
    function renderProducts() {
      const container = form.querySelector('[data-product-rows]');
      if (!container) return;
      container.replaceChildren();
      function control(parent, object, key, label, options = {}) {
        const wrapper = document.createElement('label'); wrapper.textContent = label;
        const input = document.createElement(options.choices ? 'select' : 'input');
        input.dataset.productField = key; input.setAttribute('aria-label', label);
        if (options.choices) {
          for (const value of ['', ...options.choices]) {
            const option = document.createElement('option'); option.value = value;
            option.textContent = value || 'Select'; input.appendChild(option);
          }
        } else {
          input.type = options.type || (options.number || options.percent ? 'number' : 'text');
          if (input.type === 'number') { input.min = '0'; input.step = 'any'; }
          if (options.percent) input.max = '100';
        }
        input.required = true;
        input.value = options.percent ? toPct(object[key] === '' ? null : object[key]) : (object[key] ?? '');
        input.addEventListener('input', () => {
          object[key] = options.percent ? fromPct(input.value) : options.number
            ? (input.value === '' ? '' : Number(input.value)) : input.value;
          showError(''); status();
        });
        wrapper.appendChild(input); parent.appendChild(wrapper);
      }
      (book.products || []).forEach((row, index) => {
        const section = document.createElement('details'); section.open = true;
        section.dataset.productRow = String(index);
        const title = document.createElement('summary'); title.textContent = row.type + ' / ' + (row.id || 'New contract');
        section.appendChild(title);
        const grid = document.createElement('div'); grid.className = 'rc-product-fields';
        for (const [key, label] of [['id', 'Contract ID'], ['entitlement_id', 'Entitlement'],
          ['source_ref', 'Contract source'], ['eligibility_ref', 'Eligibility evidence']]) control(grid, row, key, label);
        control(grid, row, 'start_date', 'Product start', {type:'date'});
        control(grid, row, 'end_date', 'Product end (exclusive)', {type:'date'});
        control(grid, row, 'price_eur', 'Contract price EUR', {number:true});
        const units = row.type === 'capacity_market' ? ['EUR_KW_YEAR', 'EUR_MW_YEAR'] :
          row.type === 'ancillary' ? ['EUR_MW_PERIOD'] : ['EUR_CERTIFICATE'];
        control(grid, row, 'price_unit', 'Price unit', {choices:units});
        control(grid, row, 'indexation_rate', 'Product index %/yr', {percent:true});
        if (row.type === 'rec') {
          control(grid, row, 'energy_stream_id', 'Backing energy contract');
          control(grid, row, 'certification_ref', 'Certification source');
        } else {
          for (const [key, label] of [['pool_id', 'Entitlement pool'], ['pool_source_ref', 'Pool evidence']]) control(grid, row, key, label);
          for (const [key, label] of [['pool_capacity_mw', 'Pool MW'], ['eligible_mw', 'Committed MW']]) control(grid, row, key, label, {number:true});
          for (const [key, label] of [['derating_factor', 'Derating %'], ['availability_factor', 'Availability %'], ['performance_factor', 'Performance %']])
            control(grid, row, key, label, {percent:true});
          if (row.type === 'ancillary') control(grid, row, 'service', 'Availability service');
        }
        section.appendChild(grid);
        const policy = document.createElement('p'); policy.className = 'd-context';
        policy.textContent = 'CONTRACTED / SAME_PERIOD / ' + (row.type === 'rec' ? 'ONE_PER_MWH / PROJECT_RETAINED_UNBUNDLED' :
          row.type === 'capacity_market' ? 'CONTRACTED_ELIGIBLE_MW / ACT_365_FIXED' : 'CONTRACTED_ELIGIBLE_MW / AVAILABILITY_ONLY');
        section.appendChild(policy);
        const applyAxis = document.createElement('button'); applyAxis.type = 'button';
        applyAxis.textContent = 'Use canonical periods';
        applyAxis.addEventListener('click', () => {
          if (!row.start_date || !row.end_date) { showError('Supply product tenor first.'); return; }
          const axis = JSON.parse(form.querySelector('[data-product-axis]').value);
          const previous = new Map(row.periods.map(point => [point.period_start, point]));
          row.periods = axis.filter(point => point.period_start >= row.start_date && point.period_end <= row.end_date)
            .map(point => row.type === 'rec' ? {...point, certified_mwh:previous.get(point.period_start)?.certified_mwh ?? ''} : {...point});
          showError(''); renderProducts(); status();
        });
        section.appendChild(applyAxis);
        const table = document.createElement('table'); table.className = 'd-table';
        const head = document.createElement('thead');
        const headers = document.createElement('tr');
        for (const label of ['Start', 'End (exclusive)', 'Settlement', ...(row.type === 'rec' ? ['Certified MWh'] : [])]) {
          const th = document.createElement('th'); th.textContent = label; headers.appendChild(th);
        }
        head.appendChild(headers); table.appendChild(head);
        const body = document.createElement('tbody');
        for (const point of row.periods) {
          const tr = document.createElement('tr');
          for (const key of ['period_start', 'period_end', 'settlement_date']) {
            const td = document.createElement('td'); td.textContent = point[key]; tr.appendChild(td);
          }
          if (row.type === 'rec') {
            const td = document.createElement('td'); control(td, point, 'certified_mwh', 'Certified MWh ' + point.period_start, {number:true});
            tr.appendChild(td);
          }
          body.appendChild(tr);
        }
        table.appendChild(body);
        const periods = document.createElement('details'); periods.dataset.productPeriods = '';
        const periodTitle = document.createElement('summary'); periodTitle.textContent = 'Settlement periods / ' + row.periods.length;
        periods.appendChild(periodTitle);
        const scroll = document.createElement('div'); scroll.className = 'rc-scroll'; scroll.appendChild(table);
        periods.appendChild(scroll); section.appendChild(periods);
        const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = 'Remove product';
        remove.addEventListener('click', () => {
          if (!window.confirm('Remove product from draft? Save remains manual.')) return;
          book.products.splice(index, 1);
          if (!book.products.length) { book.version = 2; delete book.products; delete book.environmental_rights; }
          renderProducts(); status();
        });
        section.appendChild(remove); container.appendChild(section);
      });
      const rights = form.querySelector('[data-product-rights]'); rights.replaceChildren();
      if (book.version !== 3) return;
      for (const row of book.environmental_rights) {
        const grid = document.createElement('div'); grid.className = 'rc-product-fields';
        control(grid, row, 'energy_stream_id', 'Energy contract ID');
        control(grid, row, 'status', 'Attribute ownership', {choices:['RETAINED_UNBUNDLED', 'TRANSFERRED_BUNDLED', 'TRANSFERRED_OTHER']});
        control(grid, row, 'source_ref', 'Ownership evidence');
        const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = 'Remove right';
        remove.addEventListener('click', () => { book.environmental_rights.splice(book.environmental_rights.indexOf(row), 1); renderProducts(); status(); });
        grid.appendChild(remove); rights.appendChild(grid);
      }
      const add = document.createElement('button'); add.type = 'button'; add.textContent = '+ Attribute right';
      add.addEventListener('click', () => { book.environmental_rights.push({energy_stream_id:'', status:'', source_ref:''}); renderProducts(); status(); });
      rights.appendChild(add);
    }
    let invalidField = null;
    function invalidRow(index, field, message) {
      invalidField = tbody.querySelector('[data-revenue-row="' + index + '"] [data-field="' + field + '"]');
      return 'Row ' + (index + 1) + ': ' + message;
    }
    function reportProblem(problem) {
      if (invalidField) {
        invalidField.setCustomValidity(problem);
        revealInvalid(invalidField);
        invalidField.setCustomValidity('');
      } else {
        showError(problem); error.scrollIntoView({block:'center'});
      }
    }
    function validate() {
      invalidField = null;
      if (book.streams.length > 24) return 'At most 24 contracts are supported.';
      if (!book.streams.length) return book.version === 3 ? 'V3 requires an explicit energy book.' : '';
      if (book.version === 3 && (!book.products.length || book.products.length > 24)) return 'V3 requires 1-24 products.';
      const seen = new Set();
      for (const [index,row] of book.streams.entries()) {
        const n = index + 1;
        if (!row.id || !row.id.trim() || row.id.length > 200 || seen.has(row.id))
          return invalidRow(index, 'id', 'contract ID is required and must be unique.');
        seen.add(row.id);
        if (!row.source_ref || !row.source_ref.trim() || row.source_ref.length > 200) {
          advancedMode(true);
          return invalidRow(index, 'source_ref', 'a source reference is required.');
        }
        const realDate = s => typeof s === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(s) &&
          Number.isFinite(Date.parse(s)) && new Date(s + 'T00:00:00Z').toISOString().slice(0,10) === s;
        if (!realDate(row.start_date)) return invalidRow(index, 'start_date', 'supply a valid start date.');
        if (!realDate(row.end_date) || row.end_date <= row.start_date)
          return invalidRow(index, 'end_date', 'supply a valid end date, after start (exclusive).');
        for (const key of ['price_eur_mwh', 'indexation_rate', 'volume_share']) {
          if (key === 'volume_share' && row.type === 'merchant' && row.volume_share === null) continue;
          const value = row[key];
          if (typeof value !== 'number' || !Number.isFinite(value) || value < 0 ||
              (key !== 'price_eur_mwh' && value > 1))
            return invalidRow(index, key, 'Values must be finite and nonnegative.');
        }
        if (row.type === 'merchant' && 'capture_rate' in row &&
            (typeof row.capture_rate !== 'number' || !Number.isFinite(row.capture_rate) ||
             row.capture_rate < 0 || row.capture_rate > 1))
          return invalidRow(index, 'capture_rate', 'merchant capture must be between 0 and 100%.');
        if (row.type === 'cfd' && (row.indexation_rate !== 0 || !row.reference_stream_id ||
             !book.streams.some(s => s.type === 'merchant' && s.id === row.reference_stream_id))) {
          advancedMode(true);
          return invalidRow(index, 'reference_stream_id', 'CfD requires a valid Merchant reference and a non-indexed strike.');
        }
        if (Array.isArray(row.price_curve)) {
          if (row.type === 'cfd' || ![2, 3].includes(book.version) || row.indexation_rate !== 0 ||
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
        if ('index_series' in row) {
          if (row.type !== 'ppa' || row.indexation_rate !== 0 || Array.isArray(row.price_curve) || ![2, 3].includes(book.version))
            return 'Row ' + n + ': an index series belongs to a version 2 PPA without an annual rate or price curve.';
          const problem = seriesProblem(row, 'Row ' + n);
          if (problem) return problem;
        } else if (!row.indexation_timing && kindOverrides.get(row) === 'indexed_ppa' && !(row.indexation_rate > 0))
          return 'Row ' + n + ': indexed PPA requires a positive annual indexation rate.';
      }
      return '';
    }
    try {
      book = safeBook(raw, form.dataset.technology, form.dataset.v3Enabled === 'true');
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
      if (isScheduled(kind) && book.version !== 3) book.version = 2;
      book.streams.push(added);
      kindOverrides.set(added, kind);
      advancedMode(true); showError(''); render(); status();
      const last = tbody.lastElementChild;
      last?.querySelector('[data-field=id]')?.focus();
    });
    // Guided "Add a PPA": builds ONE ordinary typed stream with a generated ID. Nothing is inferred - every contractual term,
    // including the contract reference, comes from the user; the existing validator and Save path stay authoritative.
    // The action is ATOMIC: every check runs first and the contract book is only touched once all of them pass.
    const quick = form.querySelector('[data-revenue-quick]');
    if (quick) {
      const q = (name) => quick.querySelector('[data-quick="' + name + '"]');
      const qErr = quick.querySelector('[data-quick-error]');
      const dates = quick.querySelector('[data-dd-root]');
      const AMOUNT = /^[-+]?(\d+\.?\d*|\.\d+)$/;
      const num = (el) => { const t = el.value.trim(); return AMOUNT.test(t) ? Number(t) : NaN; };
      const json = (name) => { try { return JSON.parse(quick.dataset[name] || '[]'); } catch (_) { return []; } };
      // Suggestions are explicit, confirmable choices (never applied silently). The first keeps the historic `data-quick-suggest` hook; any
      // alternative carries `data-quick-suggest-alt` so both sides of an unacceptable date can be offered with what each one means.
      const quickError = (message, suggestions) => {
        qErr.replaceChildren(document.createTextNode(message || ''));
        const list = Array.isArray(suggestions) ? suggestions : (suggestions ? [suggestions] : []);
        list.forEach((suggestion, i) => {
          const use = document.createElement('button');
          use.type = 'button';
          use.setAttribute(i === 0 ? 'data-quick-suggest' : 'data-quick-suggest-alt', suggestion.value);
          use.textContent = suggestion.label || ('Use ' + suggestion.value);
          use.addEventListener('click', () => {
            const el = dates.querySelector('[data-dd="' + suggestion.field + '"]');
            if (suggestion.field === 'end') { const manual = dates.querySelector('[data-dd="manual"]'); manual.checked = true; }
            el.value = suggestion.value;
            dates.ddRecalc();
            quickError('');
          });
          qErr.append(' ', use);
        });
        qErr.hidden = !message;
        return false;
      };
      const nearest = (list, target) => {
        const t = Date.parse(target + 'T00:00:00Z');
        return list.reduce((best, d) => best === null || Math.abs(Date.parse(d + 'T00:00:00Z') - t) < Math.abs(Date.parse(best + 'T00:00:00Z') - t) ? d : best, null);
      };
      const syncKind = () => {
        const kind = q('kind').value;
        const series = kind === 'indexed_ppa' && q('index_mode')?.value === 'series';
        quick.querySelector('[data-quick-index]').hidden = kind !== 'indexed_ppa' || series;
        const modeBox = quick.querySelector('[data-quick-index-mode]'); if (modeBox) modeBox.hidden = kind !== 'indexed_ppa';
        const seriesBox = quick.querySelector('[data-quick-index-series]'); if (seriesBox) seriesBox.hidden = !series;
        quick.querySelector('[data-quick-scheduled-note]').hidden = kind !== 'scheduled_ppa';
        quick.querySelector('[data-quick-price-label]').textContent = kind === 'scheduled_ppa' ? 'Starting price for every period (EUR/MWh)' : 'Starting price (EUR/MWh)';
      };
      q('kind').addEventListener('change', syncKind);
      q('index_mode')?.addEventListener('change', syncKind);
      syncKind();
      const nextId = () => { let n = 1; const used = new Set(book.streams.map(r => r.id)); while (used.has('ppa-' + n)) n += 1; return 'ppa-' + n; };
      quick.querySelector('[data-quick-add]').addEventListener('click', () => {
        if (blocked) return quickError('Editing is blocked for this configuration.');
        if (book.streams.length >= 24) return quickError('At most 24 contracts are supported.');
        window.FincoDates?.mount(dates);
        const kind = q('kind').value, scheduled = kind === 'scheduled_ppa';
        const seriesMode = kind === 'indexed_ppa' && q('index_mode')?.value === 'series';
        const price = num(q('price')), share = num(q('share')), index = kind === 'indexed_ppa' && !seriesMode ? num(q('index')) : 0;
        const ref = q('ref').value.trim();
        const span = dates.ddState();
        // 1. dates: valid, derived from start + duration (or explicit manual end), and ON the project's operating-period boundaries
        if (!span.valid) return quickError(span.message);
        const boundaries = json('boundaries');
        if (boundaries.length) {
          const starts = json('periodStarts'), windowEnd = quick.dataset.windowEnd || boundaries[boundaries.length - 1];
          const D = window.FincoDates;
          // What a candidate end date means for the contract: its term and how many operating periods it covers (end is EXCLUSIVE).
          const meaning = (from, to) => {
            const months = D ? D.impliedMonths(from, to) : null;
            const n = starts.filter(d => d >= from && d < to).length;
            return (months ? D.describe(months) + ', ' : '') + n + ' operating period' + (n === 1 ? '' : 's');
          };
          const options = (field, value, fixedOther) => {
            const earlier = boundaries.filter(d => d < value && (field === 'start' || d > fixedOther)).pop();
            const later = boundaries.find(d => d > value && (field === 'start' ? d < fixedOther : true));
            const make = (d) => ({field, value: d, label: 'Use ' + d + ' (' + (field === 'end' ? meaning(fixedOther, d) : meaning(d, fixedOther)) + ')'});
            const picks = [earlier, later].filter(Boolean).map(make);
            const near = nearest(boundaries, value);
            return picks.sort((a, b) => (a.value === near ? -1 : 0) - (b.value === near ? -1 : 0));
          };
          if (!boundaries.includes(span.start))
            return quickError('The start date ' + span.start + ' is not an operating-period boundary, so the contract cannot be saved as entered. Accepted start dates are the first day of a model operating period.', options('start', span.start, span.end));
          if (span.end > windowEnd)
            return quickError('The contract end ' + span.end + ' is after the model operating period ends (' + windowEnd + '). A contract term can be longer than the model horizon, but only the modelled operating periods are priced; choose an end on or before ' + windowEnd + '.', [{field: 'end', value: windowEnd, label: 'Use ' + windowEnd + ' (' + meaning(span.start, windowEnd) + ')'}]);
          if (!boundaries.includes(span.end))
            return quickError('The end date ' + span.end + ' is not an operating-period boundary, so the contract cannot be saved as entered. The end date is exclusive: the contract covers every operating period that starts before it. Choose one of the nearest accepted dates; the term is never rounded for you.', options('end', span.end, span.start));
        }
        // 2. operating periods inside the contract (Scheduled needs one explicit price for each)
        const periods = json('periodStarts').filter(d => d >= span.start && d < span.end);
        if (scheduled && !periods.length) return quickError('No operating periods fall inside these dates. Adjust the start date or the duration.');
        // 3. pricing, allocation, indexation and the declared contract reference
        if (!(price >= 0)) return quickError('Enter the starting price as a number, for example 62.5.');
        if (!(share > 0 && share <= 100)) return quickError('Contracted production must be above 0% and at most 100%.');
        if (kind === 'indexed_ppa' && !seriesMode && !(index >= 0 && index <= 100)) return quickError('Enter the indexation as a percentage between 0 and 100.');
        // PPA-01: the series covers one level per priced operating year, starting at the first priced year (the base). Pasted levels are parsed
        // strictly and must match the contract's years exactly; with nothing pasted the rows start empty and the contract is an incomplete draft.
        let indexSeries = null;
        if (seriesMode) {
          const years = contractYears({start_date: span.start, end_date: span.end});
          if (!years.length) return quickError('No model operating years fall inside these dates. Adjust the start date or the duration.');
          const pasted = (q('index_levels')?.value || '').trim();
          if (pasted) {
            try { indexSeries = parseIndexPaste(pasted, years[0], years.length); } catch (err) { return quickError(err.message); }
            if (indexSeries[0].operating_year > years[0]) return quickError('The first pasted year is after the first priced operating year ' + years[0] + '; the base index must be at or before it.');
            const last = indexSeries[indexSeries.length - 1].operating_year;
            if (last < years[years.length - 1]) return quickError('The pasted levels stop at operating year ' + last + ' but the contract prices through year ' + years[years.length - 1] + '. Supply every priced year; levels are never extrapolated.');
          } else {
            indexSeries = years.map(year => ({operating_year: year, level: '', basis: 'FORECAST'}));
          }
        }
        if (!ref || ref.length > 200) return quickError('Enter the contract reference (up to 200 characters).');
        // 4. build the complete contract in LOCAL state; only now is the book touched
        const added = newRow(kind);
        Object.assign(added, {id: nextId(), start_date: span.start, end_date: span.end, volume_share: share / 100,
          price_eur_mwh: price, indexation_rate: index / 100, source_ref: ref});
        if (scheduled) {
          added.price_curve = periods.map(d => ({period_start: d, price_eur_mwh: price}));
          added.price_eur_mwh = 0;
        }
        if (scheduled && book.version !== 3) book.version = 2;
        if (indexSeries) {
          added.index_series = indexSeries;
          if (book.version !== 3) book.version = 2;
        }
        book.streams.push(added);
        kindOverrides.set(added, kind);
        quickError(''); showError(''); render(); status();
        q('ref').value = ''; q('price').value = '';
        if (q('index_levels')) q('index_levels').value = '';
        // The added-note never hides an incomplete or over-allocated state reported by status().
        const clean = form.dataset.incomplete !== 'true' && form.querySelector('[data-revenue-allocation]')?.dataset.over !== 'true';
        if (clean) feedback.textContent = 'PPA added to the draft · Save contracts to update the Working Copy (Run separately)';
        if (indexSeries) {
          const editors = tbody.querySelectorAll('.rc-index-series-row .rc-index-editor');
          const editor = editors[editors.length - 1];
          if (editor) { editor.open = true; editor.scrollIntoView({block: 'nearest'}); editor.querySelector('[data-index-level]')?.focus(); }
          if (clean) feedback.textContent = 'Indexed PPA added with an index series · review the levels, then Save contracts (Run separately)';
        }
        if (scheduled) {
          if (clean) feedback.textContent = 'Scheduled PPA added · ' + periods.length + ' operating periods · review the price for each, then Save contracts';
          const rows = tbody.querySelectorAll('.rc-price-curve-row details');
          const editor = rows[rows.length - 1];
          if (editor) { editor.open = true; editor.querySelector('input[type=number]')?.focus(); editor.scrollIntoView({block: 'nearest'}); }
        }
      });
    }
    form.querySelector('[data-product-add]')?.addEventListener('click', () => {
      if ((book.products || []).length >= 24) { showError('At most 24 products.'); return; }
      if (book.version !== 3) { book.version = 3; book.products = []; book.environmental_rights = []; }
      const type = form.querySelector('[data-product-type]').value;
      const row = {id:'', type, entitlement_id:'', source_ref:'', eligibility_ref:'', start_date:'', end_date:'',
        classification:'CONTRACTED', price_eur:'', price_unit:'', indexation_rate:'', settlement:'SAME_PERIOD', periods:[]};
      if (type === 'rec') Object.assign(row, {energy_stream_id:'', certification_ref:'', certificate_basis:'ONE_PER_MWH', ownership:'PROJECT_RETAINED_UNBUNDLED'});
      else {
        Object.assign(row, {pool_id:'', pool_source_ref:'', pool_capacity_mw:'', eligible_mw:'', capacity_basis:'CONTRACTED_ELIGIBLE_MW',
          derating_factor:'', availability_factor:'', performance_factor:''});
        if (type === 'capacity_market') row.day_count = 'ACT_365_FIXED';
        else Object.assign(row, {service:'', obligation:'AVAILABILITY_ONLY'});
      }
      book.products.push(row); renderProducts(); showError(''); status();
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
        reportProblem(problem); return;
      }
      payload.value = book.streams.length ? JSON.stringify(book) : '';
    }, true);
    form.addEventListener('htmx:configRequest', event => {
      if (event.detail.elt !== form) return;
      if (event.detail.parameters.action === 'inherit') return;
      const problem = validate();
      if (problem) { event.preventDefault(); reportProblem(problem); return; }
      payload.value = book.streams.length ? JSON.stringify(book) : '';
      event.detail.parameters.contracts = payload.value;
    });
    form.addEventListener('htmx:responseError', event => {
      let message = 'Save failed. Working Copy was not changed; check the inputs and reload if the scenario moved.';
      try { message = JSON.parse(event.detail.xhr.responseText).error || message; } catch (_) {}
      // SC-04: a rejected Save never swaps the sheet, so the typed contract draft stays in the editor. A 409 (stale/changed Working Copy) says
      // so and offers an explicit Reload; the write is never replayed automatically and the persisted values are not overwritten.
      const status = event.detail.xhr.status;
      if (status === 409) {
        showError(message + ' Your unsaved contract draft is still on screen; reloading discards it.');
        const reload = document.createElement('button');
        reload.type = 'button';
        reload.setAttribute('data-conflict-reload', '');
        reload.textContent = 'Reload current values';
        reload.addEventListener('click', () => window.location.reload());
        error.appendChild(document.createTextNode(' '));
        error.appendChild(reload);
      } else {
        showError(message);
      }
      document.dispatchEvent(new CustomEvent('rc:failed', {detail: {message}}));
    });
    advancedMode(false);
    render();
    status();
  }

  document.addEventListener('htmx:afterRequest', (event) => {
    const elt = event.detail && event.detail.elt;
    if (elt && elt.matches && elt.matches('form[data-revenue-editor]') && event.detail.successful) document.dispatchEvent(new CustomEvent('rc:saved'));
  });
  // Unsaved contract edits must never disappear silently: a scenario change or a Run waits until they are saved or discarded.
  document.addEventListener('htmx:confirm', (event) => {
    const elt = event.detail && event.detail.elt;
    if (!elt || !elt.matches) return;
    const post = String(elt.getAttribute('hx-post') || '');
    const isScenario = post.indexOf('/v2/workbook/scenarios/') === 0;
    const isRun = elt.classList.contains('v2-run-form');
    if (!isScenario && !isRun) return;
    const dirty = document.querySelector('form[data-revenue-editor][data-dirty="true"]');
    if (!dirty) return;
    event.preventDefault();
    const box = dirty.querySelector('[data-revenue-error]');
    if (box) { box.textContent = isRun ? 'Save or discard the unsaved contract changes before running the model.' : 'Save or discard the unsaved contract changes before changing the scenario.'; box.hidden = false; box.scrollIntoView({block: 'nearest'}); }
  });
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
