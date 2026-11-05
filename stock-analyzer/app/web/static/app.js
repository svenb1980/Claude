// Behaviour shared by all pages: the menu and the phone view of tables.
(function () {
  "use strict";

  const toggle = document.querySelector(".menu-toggle");
  const menu = document.getElementById("site-menu");
  if (toggle && menu) {
    const setOpen = (open) => {
      toggle.setAttribute("aria-expanded", String(open));
      menu.classList.toggle("is-open", open);
    };
    toggle.addEventListener("click", () => setOpen(toggle.getAttribute("aria-expanded") !== "true"));
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && menu.classList.contains("is-open")) {
        setOpen(false);
        toggle.focus();
      }
    });
    document.addEventListener("click", (event) => {
      if (!menu.contains(event.target) && !toggle.contains(event.target)) setOpen(false);
    });
  }

  // On a phone, a wide table becomes a list of blocks. Each cell needs its column name for that.
  const MIN_COLUMNS = 4;

  function prepareTable(table) {
    if (table.dataset.prepared || table.classList.contains("matrix") || table.closest(".ask-body")) return;
    const headers = [...table.querySelectorAll("thead th")].map((th) => th.textContent.trim());
    // A table with forms in it needs the room as well.
    if (headers.length < MIN_COLUMNS && !table.querySelector("tbody form")) return;
    table.dataset.prepared = "1";
    table.classList.add("stack-table");
    table.querySelectorAll("tbody tr").forEach((row) => {
      [...row.cells].forEach((cell, index) => {
        if (!cell.children.length && !cell.textContent.trim()) cell.classList.add("is-empty");
        // A "Verwijderen" dropdown already says what it is.
        if (index > 0 && headers[index] && !cell.querySelector("details")) cell.dataset.label = headers[index];
      });
    });
  }

  function prepareAll(root) {
    root.querySelectorAll("table").forEach(prepareTable);
  }

  prepareAll(document);
  // Some tables are added later, such as the intraday levels.
  const main = document.querySelector("main");
  if (main) {
    new MutationObserver((changes) => {
      changes.forEach((change) => change.addedNodes.forEach((node) => {
        if (node.nodeType === Node.ELEMENT_NODE) {
          if (node.matches("table")) prepareTable(node);
          else prepareAll(node);
        }
      }));
    }).observe(main, { childList: true, subtree: true });
  }
})();
