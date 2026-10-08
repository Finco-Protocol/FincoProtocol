/* Scoped canonical JSON editor. No revenue calculations or lifecycle authority. */
(function () {
  'use strict';
  function init() {
    document.querySelectorAll('[data-decision-merchant]').forEach(function (form) {
      if (form.dataset.initialized) return;
      form.dataset.initialized = 'true';
      var body = form.querySelector('tbody');
      var status = form.querySelector('[role=status]');
      var json = form.querySelector('textarea[name=value]');
      var save = form.querySelector('[type=submit]');
      function dirty() { status.textContent = 'Curve edited locally. Save to update Working Copy.'; save.disabled = false; }
      function row(year, price) {
        var tr = document.createElement('tr');
        [['year',year,'Calendar year'],['price_eur_mwh',price,'Merchant price EUR/MWh']].forEach(function (parts) {
          var td = document.createElement('td'), input = document.createElement('input');
          input.type = 'number'; input.dataset.key = parts[0]; input.value = parts[1]; input.required = true;
          input.step = parts[0] === 'year' ? '1' : 'any';
          if (parts[0] === 'year') { input.min = '2000'; input.max = '2200'; } else { input.min='0'; }
          input.setAttribute('aria-label',parts[2]); input.addEventListener('input',dirty);
          td.appendChild(input); tr.appendChild(td);
        });
        var td = document.createElement('td'), remove = document.createElement('button');
        remove.type='button'; remove.textContent='\u00d7'; remove.title='Remove calendar year';
        remove.setAttribute('aria-label','Remove calendar year');
        remove.addEventListener('click',function () { tr.remove(); dirty(); });
        td.appendChild(remove); tr.appendChild(td); body.appendChild(tr);
      }
      try {
        JSON.parse(form.dataset.curve || '[]').sort(function(a,b) {return a.year-b.year;}).forEach(function(r) {row(r.year,r.price_eur_mwh);});
      } catch(e) { status.textContent='Stored curve unavailable. Enter valid calendar-year prices before saving.'; }
      form.querySelector('[data-add-year]').addEventListener('click',function () {
        var years = Array.from(body.querySelectorAll('[data-key=year]')).map(function(el){return Number(el.value);});
        var year = years.length ? Math.max.apply(null,years)+1 : Number(form.dataset.startYear);
        if (!Number.isInteger(year) || year < 2000 || year > 2200) {status.textContent='No supported additional calendar year.';return;}
        row(year,''); dirty(); body.lastChild.querySelector('[data-key=price_eur_mwh]').focus();
      });
      function serialize(e) {
        var seen = new Set(), valid=true;
        var rows = Array.from(body.children).map(function(tr) {
          var year=Number(tr.querySelector('[data-key=year]').value), priceEl=tr.querySelector('[data-key=price_eur_mwh]');
          var price=Number(priceEl.value);
          if (!Number.isInteger(year) || year<2000 || year>2200 || seen.has(year) || !priceEl.value.trim() || !Number.isFinite(price) || price<0) valid=false;
          seen.add(year); return {year:year,price_eur_mwh:price};
        });
        rows.sort(function(a,b){return a.year-b.year;});
        rows.forEach(function(r,i) { if(i && r.year!==rows[i-1].year+1) valid=false; });
        if (!valid) {
          e.preventDefault(); e.stopImmediatePropagation(); status.textContent='Use unique contiguous years 2000\u20132200 and non-negative finite prices. No changes saved.';return false;
        }
        json.value=JSON.stringify(rows.sort(function(a,b){return a.year-b.year;}));
        status.textContent='Saving curve through canonical Working Copy validation...'; return true;
      }
      form.addEventListener('submit',serialize,true);
      form.addEventListener('htmx:configRequest',function(e) { if(serialize(e)) e.detail.parameters.value=json.value; });
    });
  }
  if (!window.fincoDecisionMerchant) {
    window.fincoDecisionMerchant=init;
    document.addEventListener('DOMContentLoaded',init);
    document.addEventListener('htmx:afterSwap',init);
    document.addEventListener('htmx:afterSettle',init);
  }
  window.fincoDecisionMerchant();
})();
