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
    if (!s || !s.state) return '—';
    if (s.state === 'FRESH') {
      return s.market_state === 'HALTED' ? 'Fresh · Trading halted' : 'Fresh / Reference';
    }
    if (s.state === 'STALE') return 'Stale';
    return '—';
  }

  function apply(node, state) {
    const price = node.querySelector('[data-market-price]');
    if (price) {
      price.textContent = state.price_display || '—';
      price.title = state.price == null ? 'Official reference unavailable' :
        'Exact official reference: ' + state.price;
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
    const badge = node.querySelector('[data-market-state]');
    if (badge) badge.textContent = _stateText(state);
    document.querySelectorAll('[data-market-tab-state]').forEach(function (el) {
      el.textContent = _stateText(state);
    });
    const observed = node.querySelector('[data-market-observed]');
    if (observed) observed.textContent = state.observed_at ? 'Observed ' + state.observed_at : '';
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
