/* Planon Verlof Goedkeurder — content script
 * Flow in Planon Self-Service (Wicket, AJAX-navigatie):
 *   lijst "Requests to approve" -> regel klikken -> "Details leave request" -> Approve / Reject / Back
 * Per aanvraag wordt eerst gecontroleerd of "# Hours" klopt met From/Till; alleen bij een match wordt goedgekeurd.
 * Zodra de lijst opent start de controle + goedkeuring vanzelf (instelbaar). Na elke run gaat een rapport via
 * background.js en bridge.js naar Cyberdeck: wie, welke periode, hoeveel uur en wat er met de aanvraag gebeurd is.
 */
(() => {
  if (window.__plvLoaded) return;
  window.__plvLoaded = true;

  // ---------- instellingen ----------
  const DEFAULTS = {
    dayStart: "08:30",      // begin werkdag (08:30–17:00 = 8 uur incl. 0,5 uur pauze)
    dayEnd: "17:00",        // einde werkdag
    breakStart: "12:30",    // pauze 0,5 uur (afgetrokken als het verlof de pauze overlapt)
    breakEnd: "13:00",      // gelijk aan breakStart = geen pauze-aftrek
    skipWeekends: true,
    tolerance: 0.01,
    autoRun: true,          // controleren + goedkeuren starten zodra de lijst opent
    autoConfirm: true       // eventuele bevestigingsstap na "Approve" automatisch klikken
  };
  let cfg = { ...DEFAULTS };

  const store = {
    async get() {
      try {
        if (window.chrome?.storage?.local) {
          const r = await chrome.storage.local.get("plvCfg2");
          return r.plvCfg2 || {};
        }
      } catch (e) {}
      try { return JSON.parse(localStorage.getItem("plvCfg2") || "{}"); } catch (e) { return {}; }
    },
    async set(v) {
      try { if (window.chrome?.storage?.local) return await chrome.storage.local.set({ plvCfg2: v }); } catch (e) {}
      try { localStorage.setItem("plvCfg2", JSON.stringify(v)); } catch (e) {}
    }
  };

  // ---------- helpers ----------
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const txt = (el) => (el?.innerText || el?.textContent || "").replace(/\s+/g, " ").trim();
  async function waitFor(fn, timeout = 15000, step = 200) {
    const t0 = Date.now();
    while (Date.now() - t0 < timeout) {
      if (state.stop) throw new Error("Gestopt door gebruiker");
      const v = fn();
      if (v) return v;
      await sleep(step);
    }
    throw new Error("Time-out bij wachten op pagina");
  }
  function realClick(el) {
    el.scrollIntoView({ block: "center" });
    try { el.focus({ preventScroll: true }); } catch (e) {}
    const r = el.getBoundingClientRect();
    const o = { bubbles: true, cancelable: true, view: window, button: 0, clientX: r.left + 5, clientY: r.top + 5 };
    for (const t of ["pointerdown", "mousedown", "pointerup", "mouseup", "click"]) {
      el.dispatchEvent(t.startsWith("pointer") ? new PointerEvent(t, o) : new MouseEvent(t, o));
    }
  }
  const hm = (s) => { const [h, m] = s.split(":").map(Number); return h * 60 + m; };

  const MONTHS = {
    january: 0, february: 1, march: 2, april: 3, may: 4, june: 5, july: 6, august: 7, september: 8, october: 9, november: 10, december: 11,
    januari: 0, februari: 1, maart: 2, mei: 4, juni: 5, juli: 6, augustus: 7, oktober: 9
  };
  function parseDate(s) {
    s = (s || "").trim();
    let m = s.match(/(\d{1,2})[\/\-.](\d{1,2})[\/\-.](\d{4})\s+(\d{1,2}):(\d{2})/);       // 30/09/2026 13:00
    if (m) return new Date(+m[3], +m[2] - 1, +m[1], +m[4], +m[5]);
    m = s.match(/(\d{1,2})\s+([A-Za-zé]+)\s+(\d{4})\s+(\d{1,2}):(\d{2})/);                 // 30 September 2026 13:00
    if (m && MONTHS[m[2].toLowerCase()] !== undefined) return new Date(+m[3], MONTHS[m[2].toLowerCase()], +m[1], +m[4], +m[5]);
    return null;
  }
  const fmtH = (h) => (Math.round(h * 100) / 100).toString().replace(".", ",") + "u";
  const sameMoment = (a, b) => a && b && a.getTime() === b.getTime();

  // verwachte uren op basis van From/Till
  function expectedHours(from, till) {
    if (!from || !till || till <= from) return null;
    const dS = hm(cfg.dayStart), dE = hm(cfg.dayEnd), bS = hm(cfg.breakStart), bE = hm(cfg.breakEnd);
    const minutesOf = (d) => d.getHours() * 60 + d.getMinutes();
    const overlap = (a1, a2, b1, b2) => Math.max(0, Math.min(a2, b2) - Math.max(a1, b1));
    const sameDay = from.toDateString() === till.toDateString();
    let total = 0;
    const day = new Date(from.getFullYear(), from.getMonth(), from.getDate());
    const last = new Date(till.getFullYear(), till.getMonth(), till.getDate());
    while (day <= last) {
      const wd = day.getDay();
      const isFirst = day.toDateString() === from.toDateString();
      const isLast = day.toDateString() === last.toDateString();
      if (sameDay || !(cfg.skipWeekends && (wd === 0 || wd === 6))) {
        const s = isFirst ? minutesOf(from) : dS;
        const e = isLast ? minutesOf(till) : dE;
        if (e > s) total += (e - s) - (bE > bS ? overlap(s, e, bS, bE) : 0);
      }
      day.setDate(day.getDate() + 1);
    }
    return total / 60;
  }

  // ---------- pagina-herkenning ----------
  function listRows() {
    return [...document.querySelectorAll("tr.aria_row[role=row]")]
      .map((tr) => {
        const c = (n) => txt(tr.querySelector(`td[data-column-name="${n}"]`));
        return { tr, type: c("Type"), requestor: c("Requestor"), number: c("Request number"), from: c("From"), till: c("Till"), status: c("Status") };
      })
      .filter((r) => r.number);
  }
  const isList = () => listRows().length > 0 || /requests to approve/i.test(txt(document.querySelector("h1,h2")) + document.title) && !isDetail();
  const approveBtn = () => document.querySelector('a.pss_action[aria-label="Approve"], a.pss_action[class*="usraccepted"]');
  const backBtn = () => document.querySelector('a.pss_actionname_back, a.pss_action[aria-label="Back"]');
  const isDetail = () => !!(approveBtn() && document.querySelector(".pss_fieldname_begindatetime"));

  function field(name) {
    const el = document.querySelector(".pss_fieldname_" + name);
    if (!el) return "";
    const lines = (el.innerText || "").split("\n").map((s) => s.trim()).filter(Boolean);
    return lines.length > 1 ? lines.slice(1).join(" ") : lines[0] || "";
  }
  function readDetail() {
    const hoursRaw = field("freedecimal2");
    return {
      requestor: field("internalrequestorpersonref"),
      from: parseDate(field("begindatetime")),
      till: parseDate(field("enddatetime")),
      hours: parseFloat(hoursRaw.replace(",", ".")),
      hoursRaw
    };
  }

  // ---------- state ----------
  const state = { running: false, stop: false, results: {}, selected: {}, handled: new Set(), log: [] };
  function log(msg) {
    const t = new Date().toLocaleTimeString("nl-NL");
    state.log.push(`[${t}] ${msg}`);
    console.log("[PLV]", msg);
    render();
  }

  // ---------- acties ----------
  async function openRow(number) {
    const row = await waitFor(() => listRows().find((r) => r.number === number), 10000);
    realClick(row.tr.querySelector('td[data-column-name="Request number"]') || row.tr.querySelector("td"));
    await waitFor(isDetail);
    await sleep(300);
    return row;
  }
  async function goBack() {
    const b = backBtn();
    if (b) realClick(b);
    await waitFor(() => !isDetail() && listRows().length >= 0 && isList(), 15000);
    await sleep(300);
  }

  function checkDetail(row) {
    const d = readDetail();
    const rowFrom = parseDate(row.from), rowTill = parseDate(row.till);
    if (!sameMoment(d.from, rowFrom) || !sameMoment(d.till, rowTill)) {
      return { ok: false, msg: "Geopende aanvraag hoort niet bij deze regel (From/Till wijkt af)",
        reason: "the opened request didn't match the row in the list (From/Till differ)" };
    }
    const exp = expectedHours(d.from, d.till);
    if (exp === null || isNaN(d.hours)) return { ok: false, msg: `Kan uren niet bepalen (# Hours: "${d.hoursRaw}")`,
      reason: `couldn't work out the hours (# Hours: "${d.hoursRaw}")` };
    const ok = Math.abs(exp - d.hours) <= cfg.tolerance;
    const h = (n) => (Math.round(n * 100) / 100) + "h";
    return { ok, hours: d.hours, expected: exp, msg: ok ? `${fmtH(d.hours)} = ${fmtH(exp)}` : `${fmtH(d.hours)} ≠ ${fmtH(exp)} (From/Till)`,
      reason: ok ? `${h(d.hours)} = ${h(exp)}` : `# Hours says ${h(d.hours)}, but From/Till gives ${h(exp)}` };
  }

  function confirmCandidates() {
    return [...document.querySelectorAll("a.pss_action, button, input[type=submit], input[type=button]")]
      .filter((b) => b.offsetParent !== null && !b.closest("#plv-panel"))
      .filter((b) => !/back|cancel|annuleer|terug|reject|afwijzen|close|sluit/i.test(txt(b) + " " + (b.value || "") + " " + (b.getAttribute("aria-label") || "")));
  }

  async function approveCurrent(row) {
    realClick(approveBtn());
    // wacht tot de detailpagina met Approve weg is
    await waitFor(() => !isDetail(), 15000);
    await sleep(500);
    if (!isList()) {
      // er is een vervolg-/bevestigingsstap
      const cands = confirmCandidates();
      const preferred = cands.filter((b) => /^(ok|save|opslaan|confirm|bevestig(en)?|approve|goedkeuren|submit|send|verzenden|finish|gereed)$/i.test(txt(b) || b.value || ""));
      if (cfg.autoConfirm && preferred.length === 1) {
        log(`Bevestigingsstap: klik "${txt(preferred[0]) || preferred[0].value}"`);
        realClick(preferred[0]);
      } else {
        (preferred[0] || cands[0])?.classList.add("plv-highlight");
        log(`Bevestigingsstap gevonden voor ${row.number}. Bevestig handmatig op de pagina; daarna gaat de extensie verder.`);
        state.waiting = true; render();
      }
      await waitFor(isList, 10 * 60 * 1000);
      state.waiting = false;
      document.querySelectorAll(".plv-highlight").forEach((e) => e.classList.remove("plv-highlight"));
      await sleep(500);
    }
    const still = listRows().find((r) => r.number === row.number);
    return !still || still.status !== row.status;
  }

  // ---------- rapport voor Cyberdeck ----------
  const iso = (s) => parseDate(s)?.toISOString() || "";
  function reportEntry(row, chk, outcome) {
    return {
      number: row.number, requestor: row.requestor, from: iso(row.from), till: iso(row.till), fromText: row.from, tillText: row.till,
      hours: chk?.hours ?? null, expected: chk?.expected ?? null, msg: chk?.reason || "", outcome
    };
  }
  async function sendReport(report) {
    try {
      await chrome.runtime.sendMessage({ action: "saveReport", report });
      log("Rapport naar Cyberdeck gestuurd.");
    } catch (e) {
      log("Rapport kon niet naar Cyberdeck (extensie herladen? ververs de pagina).");
    }
  }

  async function run(doApprove, auto = false) {
    if (state.running) return;
    state.running = true; state.stop = false; render();
    const rows = listRows().filter((r) => state.selected[r.number] !== false && /leave/i.test(r.type));
    rows.forEach((r) => state.handled.add(r.number));
    const report = { id: `leave-${Date.now()}`, auto, approve: doApprove, page: location.href, fatal: "", stopped: false, requests: [] };
    const reported = new Set();
    let current = null; // aanvraag waarop Approve al geklikt is, maar nog niet gerapporteerd
    log(`${auto ? "Automatisch: " : ""}${doApprove ? "Controleren + goedkeuren" : "Alleen controleren"}: ${rows.length} aanvraag/aanvragen`);
    try {
      for (const { number: num } of rows) {
        if (state.stop) break;
        const row = await openRow(num);
        const chk = checkDetail(row);
        state.results[num] = { ...chk, state: chk.ok ? "gecontroleerd" : "afgekeurd door controle" };
        log(`${num} ${row.requestor} ${row.from}–${row.till.split(" ")[1] || row.till}: ${chk.ok ? "✓" : "✗"} ${chk.msg}`);
        let outcome = chk.ok ? "checked" : "check-failed";
        if (doApprove && chk.ok) {
          current = { row, chk };
          const done = await approveCurrent(row);
          outcome = done ? "approved" : "unknown";
          state.results[num].state = done ? "goedgekeurd" : "status onbekend — controleer";
          log(`${num}: ${state.results[num].state}`);
        }
        report.requests.push(reportEntry(row, chk, outcome));
        reported.add(num); current = null;
        if (outcome === "checked" || outcome === "check-failed" || !isList()) await goBack();
        render();
      }
      log("Klaar.");
    } catch (e) {
      log("Fout: " + e.message);
      if (!state.stop) report.fatal = e.message;
    } finally {
      report.stopped = state.stop;
      if (current) { report.requests.push(reportEntry(current.row, current.chk, "unknown")); reported.add(current.row.number); }
      for (const r of rows) if (!reported.has(r.number)) report.requests.push(reportEntry(r, null, "not-done"));
      report.finishedAt = Date.now();
      state.running = false; state.stop = false; state.waiting = false; render();
      sendReport(report);
    }
  }

  // Automatisch starten zodra de lijst aanvragen toont die in deze sessie nog niet behandeld zijn.
  // Een aanvraag die niet door de controle kwam blijft staan, maar wordt pas na verversen opnieuw bekeken.
  let autoTimer = null, armedRun = false;
  function maybeAutoRun() {
    if (state.running || autoTimer || !(cfg.autoRun || armedRun) || !isList() || isDetail()) return;
    const fresh = listRows().filter((r) => /leave/i.test(r.type) && state.selected[r.number] !== false && !state.handled.has(r.number));
    if (!fresh.length) return;
    autoTimer = setTimeout(() => { // laat Planon eerst uitrenderen
      autoTimer = null;
      if (state.running || !isList() || isDetail()) return;
      armedRun = false;
      run(true, true);
    }, 2000);
  }

  // ---------- paneel ----------
  let panel, minimized = false, confirmArm = false;
  function ensurePanel() {
    if (panel && document.documentElement.contains(panel)) return;
    panel = document.createElement("div");
    panel.id = "plv-panel";
    document.documentElement.appendChild(panel);
    panel.addEventListener("click", onPanelClick);
    panel.addEventListener("change", onPanelChange);
  }
  function esc(s) { return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

  function render() {
    const onList = isList() && !isDetail();
    if (!onList && !state.running) { if (panel) panel.style.display = "none"; return; }
    ensurePanel();
    panel.style.display = "";
    panel.classList.toggle("plv-min", minimized);
    const rows = onList ? listRows() : [];
    const rowsHtml = rows.map((r) => {
      const res = state.results[r.number];
      const sel = state.selected[r.number] !== false;
      const resHtml = res ? `<span class="${res.ok ? "ok" : "bad"}">${res.ok ? "✓" : "✗"} ${esc(res.msg)}</span><br><span class="muted">${esc(res.state)}</span>` : `<span class="muted">nog niet gecontroleerd</span>`;
      return `<tr><td><input type="checkbox" data-num="${esc(r.number)}" ${sel ? "checked" : ""} ${state.running ? "disabled" : ""}></td>
        <td>${esc(r.requestor)}<br><span class="muted">${esc(r.number.replace(/\.00$/, ""))}</span></td>
        <td>${esc(r.from)}<br><span class="muted">t/m ${esc(r.till)}</span></td><td>${resHtml}</td></tr>`;
    }).join("");
    panel.innerHTML = `
      <div class="plv-head" data-act="toggle"><b>Verlof goedkeuren</b><span>${state.running ? (state.waiting ? "⏸ wacht op bevestiging" : "⏳ bezig…") : minimized ? "▲" : "▼"}</span></div>
      <div class="plv-body">
        ${onList ? `<table><tr><th></th><th>Aanvrager</th><th>Periode</th><th>Uren-controle</th></tr>${rowsHtml || '<tr><td colspan="4" class="muted">Geen aanvragen</td></tr>'}</table>` : '<p class="muted">Bezig met aanvraag…</p>'}
        <div class="plv-btns">
          <button class="sec" data-act="check" ${state.running ? "disabled" : ""}>Alleen controleren</button>
          <button data-act="approve" ${state.running ? "disabled" : ""}>${confirmArm ? "Zeker? Klik nogmaals" : "Controleren + goedkeuren"}</button>
          ${state.running ? '<button class="stop" data-act="stop">Stop</button>' : ""}
        </div>
        <details><summary>Instellingen urencontrole</summary>
          <label>Werkdag <input type="time" data-cfg="dayStart" value="${cfg.dayStart}"> – <input type="time" data-cfg="dayEnd" value="${cfg.dayEnd}"></label>
          <label>Pauze <input type="time" data-cfg="breakStart" value="${cfg.breakStart}"> – <input type="time" data-cfg="breakEnd" value="${cfg.breakEnd}"> <span class="muted">(gelijk = geen aftrek)</span></label>
          <label><input type="checkbox" data-cfg="autoRun" ${cfg.autoRun ? "checked" : ""}> Automatisch controleren + goedkeuren zodra de lijst opent</label>
          <label><input type="checkbox" data-cfg="skipWeekends" ${cfg.skipWeekends ? "checked" : ""}> Weekenddagen niet meetellen (meerdaags)</label>
          <label><input type="checkbox" data-cfg="autoConfirm" ${cfg.autoConfirm ? "checked" : ""}> Eventuele bevestigingsstap na Approve automatisch klikken</label>
        </details>
        <details ${state.log.length ? "open" : ""}><summary>Log</summary><div class="plv-log">${esc(state.log.slice(-60).join("\n"))}</div></details>
      </div>`;
    const lg = panel.querySelector(".plv-log"); if (lg) lg.scrollTop = lg.scrollHeight;
    maybeAutoRun();
  }

  function onPanelClick(e) {
    const act = e.target.closest("[data-act]")?.dataset.act;
    if (!act) return;
    e.preventDefault(); e.stopPropagation();
    if (act === "toggle") { minimized = !minimized; render(); }
    if (act === "check") { confirmArm = false; run(false); }
    if (act === "approve") {
      if (!confirmArm) { confirmArm = true; render(); setTimeout(() => { confirmArm = false; render(); }, 4000); return; }
      confirmArm = false; run(true);
    }
    if (act === "stop") { state.stop = true; log("Stoppen na huidige stap…"); }
  }
  function onPanelChange(e) {
    const t = e.target;
    if (t.dataset.num) { state.selected[t.dataset.num] = t.checked; return; }
    if (t.dataset.cfg) {
      cfg[t.dataset.cfg] = t.type === "checkbox" ? t.checked : t.value;
      store.set(cfg);
      if (t.dataset.cfg !== "autoRun") state.results = {}; // urenregels gewijzigd -> opnieuw controleren
      render();
    }
  }

  // ---------- start ----------
  let pending;
  const mo = new MutationObserver((muts) => {
    if (muts.every((m) => panel && panel.contains(m.target))) return;
    clearTimeout(pending);
    pending = setTimeout(render, 250);
  });
  const takeArmed = async () => { // Cyberdeck vroeg om een run (klik op een Planon-link), geldig 10 minuten
    try {
      const { plvArmed = 0 } = await chrome.storage.local.get("plvArmed");
      if (Date.now() - plvArmed < 10 * 60 * 1000) { armedRun = true; await chrome.storage.local.remove("plvArmed"); }
    } catch (e) {}
  };
  Promise.all([store.get(), takeArmed()]).then(([saved]) => {
    cfg = { ...DEFAULTS, ...saved };
    mo.observe(document.body, { childList: true, subtree: true });
    render();
  });

  // voor testen vanuit de console
  window.__plv = { state, expectedHours, parseDate, readDetail, listRows, run };
})();
