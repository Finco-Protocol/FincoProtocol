/* Developer Economics editor: add/remove spend rows only. No financial logic, no server writes. */
(function () {
  var body = document.getElementById("dd-spend-rows");
  if (!body) return;
  function blank() {
    var row = body.querySelector("[data-spend-row]");
    if (!row) return null;
    var copy = row.cloneNode(true);
    copy.querySelectorAll("input").forEach(function (i) { i.value = ""; });
    return copy;
  }
  document.addEventListener("click", function (event) {
    var remove = event.target.closest("[data-remove-row]");
    if (remove) {
      var row = remove.closest("[data-spend-row]");
      if (body.querySelectorAll("[data-spend-row]").length > 1) { row.remove(); }
      else { row.querySelectorAll("input").forEach(function (i) { i.value = ""; }); }
      return;
    }
    if (event.target.closest("[data-add-row]")) {
      var added = blank();
      if (added) { body.appendChild(added); added.querySelector("input").focus(); }
    }
  });
})();
