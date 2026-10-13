// M3 two-driver sensitivity matrix: HTMX does not swap 4xx responses by default. The matrix route marks its typed,
// user-facing error fragments (validation, unsupported driver, stale context) with X-Finco-Matrix-Error so they are
// shown in the results area instead of being dropped silently. Nothing else changes; no financial logic lives here.
(function () {
  if (window.__finco_matrix_error_swap) return;
  window.__finco_matrix_error_swap = true;
  document.addEventListener('htmx:beforeSwap', function (event) {
    var xhr = event && event.detail && event.detail.xhr;
    if (xhr && typeof xhr.getResponseHeader === 'function' && xhr.getResponseHeader('X-Finco-Matrix-Error') === '1') {
      event.detail.shouldSwap = true;
      event.detail.isError = false;
    }
  });
}());
