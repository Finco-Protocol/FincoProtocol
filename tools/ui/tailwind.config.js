/* Flowbite + Tailwind layer for the FINCO Model workspace (self-hosted, built once, output committed).
 * - `important: '.fx-ui'`  : every utility is scoped to a `.fx-ui` container, so the existing FINCO CSS is never overridden elsewhere.
 * - preflight disabled     : Tailwind's global reset is NOT loaded; existing page styles are untouched.
 * - Flowbite plugin forms/tooltips off: their global base styles would restyle every input in the application.
 * - dark mode follows the same two signals as static/css/model_tokens.css (OS preference unless data-theme="light"; or data-theme="dark").
 */
module.exports = {
  important: '.fx-ui',
  corePlugins: { preflight: false },
  darkMode: ['variant', ['@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) & }', ':root[data-theme="dark"] &']],
  content: [
    '../../app/templates/v2/**/*.html',
    '../../static/js/fx_ui.js',
    '../../static/js/model_revenue_contract_editor.js',
    '../../static/js/construction_timing.js',
  ],
  theme: { extend: {} },
  plugins: [require('flowbite/plugin')({ forms: false, tooltips: false, charts: false, datatables: false })],
};
