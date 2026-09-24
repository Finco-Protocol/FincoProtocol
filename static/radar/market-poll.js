/* Read-only market references. One board request or one selected-asset request. */
(function () {
  'use strict';
  const board = document.getElementById('featured-board');
  const terminal = document.querySelector('[data-market-terminal-uid]');
  const uid = terminal && terminal.dataset.marketTerminalUid;
  if (!board && !uid) return;
  let timer = null;
  let active = null;
  let stopped = false;
  const cadence = board ? 12000 : 8000;

  function _stateText(s) {
    if (!s || !s.state) return 'UNAVAILABLE';
    if (s.state === 'FRESH') {
      return s.market_state === 'HALTED' ? 'HALTED' : 'FRESH / REFERENCE';
    }
    if (s.state === 'STALE') return 'STALE';
    return 'UNAVAILABLE';
  }

  function _compactMarketText(s) {
    if (!s || s.state !== 'FRESH') return _stateText(s);
    if (s.market_state === 'HALTED') return 'HALTED';
    const observed = s.observed_at ? new Date(s.observed_at) : null;
    const time = observed && !Number.isNaN(observed.getTime()) ? observed.toLocaleTimeString('en-GB', {
      timeZone: 'UTC', hour: '2-digit', minute: '2-digit', hour12: false
    }) + ' UTC' : 'time unavailable';
    return '● REF · ' + time;
  }

  function _marketTitle(s) {
    return [
      'Observed at: ' + (s.observed_at || 'UNAVAILABLE'),
      'Reference state: ' + (s.market_state || 'UNAVAILABLE'),
      'Freshness: ' + (s.state || 'UNAVAILABLE'),
      'Source: ' + (s.source || 'UNAVAILABLE')
    ].join('\n');
  }

  function apply(node, state) {
    // The Featured board is an operational shortlist, not an error report.
    // A row remains visible only when it has both a canonical asset UID and a
    // fresh official market reference.  Missing/ambiguous identity therefore
    // stays fail-closed even if a symbol-only market row happens to exist.
    if (node.matches && node.matches('[data-featured-row]')) {
      const hasCanonicalIdentity = !!(node.dataset.marketUid || '').trim();
      const usableReference = hasCanonicalIdentity && !!state && state.state === 'FRESH' && state.price != null;
      node.hidden = !usableReference;
    }
    const price = node.querySelector('[data-market-price]');
    if (price) {
      price.textContent = state.price_display || '—';
      price.title = state.price == null ? 'Official reference unavailable\n' + _marketTitle(state) :
        'Exact official reference: ' + state.price + '\n' + _marketTitle(state);
    }
    // Tab-panel price elements outside the terminal header section.
    document.querySelectorAll('[data-market-tab-price]').forEach(function (el) {
      el.textContent = state.price_display || '—';
      el.title = state.price == null ? 'Official reference unavailable' :
        'Exact official reference: ' + state.price;
    });
    document.querySelectorAll('[data-market-bid]').forEach(function (bid) {
      bid.textContent = state.bid_display || (state.bid != null ? state.bid : '—');
    });
    document.querySelectorAll('[data-market-ask]').forEach(function (ask) {
      ask.textContent = state.ask_display || (state.ask != null ? state.ask : '—');
    });
    document.querySelectorAll('[data-market-source]').forEach(function (source) {
      source.textContent = state.source ? 'Source ' + state.source : 'Source unavailable';
    });
    const badge = node.querySelector('[data-market-state]');
    if (badge) { badge.textContent = _compactMarketText(state); badge.title = _marketTitle(state); }
    document.querySelectorAll('[data-market-tab-state]').forEach(function (el) {
      el.textContent = _stateText(state);
    });
    const observed = node.querySelector('[data-market-observed]');
    if (observed) { observed.textContent = ''; observed.title = _marketTitle(state); }
    document.querySelectorAll('[data-market-tab-observed]').forEach(function (el) {
      el.textContent = state.observed_at ? 'Observed ' + state.observed_at : '';
    });
  }

  async function tick() {
    if (stopped || document.hidden) return;
    active = new AbortController();
    try {
      const url = board ? '/radar/market/board' :
        '/radar/market/asset/' + encodeURIComponent(uid);
      const response = await fetch(url, {signal: active.signal, cache: 'no-store'});
      if (!response.ok) throw new Error('Market read unavailable');
      const payload = await response.json();
      if (board) {
        const rows = new Map((payload.assets || []).map(function (row) { return [row.symbol, row]; }));
        board.querySelectorAll('[data-market-uid]').forEach(function (node) {
          const row = rows.get(node.dataset.marketSymbol);
          if (row) apply(node, row);
          else if (node.matches('[data-featured-row]')) node.hidden = true;
        });
        const status = board.querySelector('[data-market-board-state]');
        if (status && payload.board) {
          const state = payload.board;
          const stale = (payload.assets || []).find(function (row) { return row.state === 'STALE' && row.observed_at; });
          if (state.state === 'UNAVAILABLE') status.textContent = 'Market data unavailable.';
          else if (state.stale_count || state.unavailable_count) {
            status.textContent = 'Showing stale or partial market reference' +
              (stale ? ' · last observed ' + stale.observed_at : '') + '.';
          } else if (state.refreshed_at) {
            status.textContent = 'Updated ' + new Date(state.refreshed_at).toLocaleTimeString('en-GB',
              {timeZone: 'UTC', hour12: false}) + ' UTC.';
          } else status.textContent = 'Market data unavailable.';
        }
      } else if (payload.asset && payload.asset.uid === uid) {
        apply(terminal, payload.asset);
      }
    } catch (error) {
      if (error.name !== 'AbortError') {
        const status = board ? board.querySelector('[data-market-board-state]') :
          terminal.querySelector('[data-market-state]');
        if (status) {
          const hasValue = board ? !!board.querySelector('[data-market-price]:not(:empty)') &&
            Array.from(board.querySelectorAll('[data-market-price]')).some(function (node) { return node.textContent !== '—'; }) :
            !!terminal.querySelector('[data-market-price]') && terminal.querySelector('[data-market-price]').textContent !== '—';
          status.textContent = hasValue ? 'Market refresh unavailable; last observed value shown.' : 'Market data unavailable.';
        }
      }
    } finally {
      active = null;
      if (!stopped && !document.hidden) timer = setTimeout(tick, cadence);
    }
  }

  document.addEventListener('visibilitychange', function () {
    clearTimeout(timer);
    if (document.hidden) {
      if (active) active.abort();
    } else {
      tick();
    }
  });
  window.addEventListener('pagehide', function () {
    stopped = true;
    clearTimeout(timer);
    if (active) active.abort();
  });
  tick();
}());
