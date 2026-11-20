// Project agent: the Projects view at the top of Your actions, opened and closed with the Projects button in the toolbar.
// A scheduled Claude task (project-agent/prompts/weekcheck.md in the repo) writes data/users/<you>/projectstatus every
// Monday at 07:15; the format is in project-agent/projectstatus-format.md. Settings › Project agent edits
// data/users/<you>/projectsettings: which page belongs to a project, and extra Jira keys.
// Whether the view is open is remembered in this browser (ad.projectsOpen).
// A plain script like the others; it uses esc, safeUrl, store and now from state.js and keeps everything else to itself.
(() => {
  const box = document.getElementById("projects");
  const btn = document.getElementById("btn-projects");
  if (!box || !btn) return;
  let status = null;   // the latest projectstatus document, or null
  let loaded = false;  // the store has answered, so "no check yet" is true and not "still loading"
  let noStore = false; // this view has no claude.ai storage (opened outside claude.ai)
  let drawn = "";
  let open = store.get("ad.projectsOpen", false) === true;
  const RAG = { red: "Red", amber: "Amber", green: "Green" };
  const RANK = { red: 0, amber: 1, green: 2 };
  const TREND = { new: "First check", better: "▲ Better", same: "No change", worse: "▼ Worse" };
  const LEVEL = { red: "Red", amber: "Amber", info: "Info" };
  const DAY = 86400000;
  const KEY_RE = /\b([A-Z][A-Z0-9]{1,9}-\d{1,7})\b/g;
  const list = (a, n) => Array.isArray(a) ? a.filter(x => x && typeof x === "object").slice(0, n) : [];
  const str = (v, n) => typeof v === "string" ? v.slice(0, n || 300) : "";
  const int = v => Number.isFinite(+v) ? Math.floor(+v) : 0;
  const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
  const midnight = d => new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const parseDay = s => { const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(str(s, 10)); return m ? new Date(+m[1], +m[2] - 1, +m[3]) : null; };
  const fmtDay = d => d.toLocaleDateString([], { day: "numeric", month: "short", year: d.getFullYear() !== now().getFullYear() ? "numeric" : undefined });
  const link = (text, url, cls) => {
    const u = safeUrl(url), c = cls ? ` class="${cls}"` : "";
    return u ? `<a${c} href="${esc(u)}" target="_blank" rel="noopener">${esc(text)}</a>` : `<span${c}>${esc(text)}</span>`;
  };
  // Jira keys in a sentence become links to the issue, on the same site as the project's Jira link.
  const browseBase = p => { try { const u = safeUrl(p && p.jira && p.jira.link); return u ? new URL(u).origin + "/browse/" : ""; } catch { return ""; } };
  const withKeys = (text, base) => esc(text).replace(KEY_RE, k => base ? `<a href="${esc(base + k)}" target="_blank" rel="noopener">${k}</a>` : k);
  const projects = () => list(status && status.projects, 20).filter(p => str(p.name, 120).trim());
  const ageDays = () => { const at = new Date(str(status && status.createdAt, 40)); return isNaN(at.getTime()) ? 0 : Math.round((midnight(now()) - midnight(at)) / DAY); };
  const say = (msg, undo) => { if (typeof toast === "function") toast(msg, undo ? { undo } : undefined); };

  function stamp() {
    const at = new Date(str(status && status.createdAt, 40));
    if (isNaN(at.getTime())) return "";
    const wk = /W(\d{1,2})$/.exec(str(status.week, 10));
    return (wk ? `Week ${+wk[1]} · ` : "") + at.toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" })
      + " " + at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function deadline(p) {
    const d = p.deadline && typeof p.deadline === "object" ? p.deadline : {};
    const day = parseDay(d.date);
    if (!day) return `<p class="pj-due none">No end date</p>`;
    const left = Math.round((day - midnight(now())) / DAY);
    const when = left < 0 ? `${plural(-left, "day")} overdue` : left === 0 ? "due today" : `in ${plural(left, "day")}`;
    const src = { PAF: "PAF page", milestone: "next milestone", roadmap: "roadmap" }[d.source] || "";
    const label = str(d.label, 40);
    const prev = parseDay(d.previous);
    return `<p class="pj-due${left < 0 ? " late" : left <= 28 ? " soon" : ""}">Due <span class="pj-date">${d.approx ? "≈ " : ""}${esc(fmtDay(day))}</span>`
      + `${label ? ` · ${esc(label)}` : ""} · ${esc(when)}${src ? ` <span class="pj-src">· ${esc(src)}</span>` : ""}`
      + `${prev ? ` <span class="pj-moved">moved from ${esc(fmtDay(prev))}</span>` : ""}</p>`;
  }

  function progress(p) {
    const g = p.progress && typeof p.progress === "object" ? p.progress : {};
    const total = Math.max(0, int(g.total)), done = Math.min(total, Math.max(0, int(g.done))), parked = Math.max(0, int(g.parked));
    const parkedNote = parked ? ` · ${parked} parked` : "";
    if (!total) return parked ? `<p class="pj-bar-t">No open work items${parkedNote}</p>` : "";
    return `<div class="pj-bar" role="img" aria-label="${done} of ${total} items done"><span style="width:${Math.round(done / total * 100)}%"></span></div>`
      + `<p class="pj-bar-t"><b>${done}</b> of ${plural(total, "item")} done${parkedNote}</p>`;
  }

  const attRow = (a, base) => {
    const lvl = LEVEL[a.level] ? a.level : "info", text = str(a.text, 400), u = safeUrl(a.link);
    const hasKey = new RegExp(KEY_RE.source).test(text);
    return `<li class="pj-att ${lvl}"><span class="pj-lvl"></span><span><span class="sr-only">${LEVEL[lvl]}: </span>${withKeys(text, base)}`
      + `${u && !hasKey ? ` ${link("Open", u)}` : ""}</span></li>`;
  };
  const itemRow = x => {
    const idle = Math.max(0, int(x.idle)), owner = str(x.owner, 80), rel = str(x.release, 20);
    return `<li>${link(str(x.key, 20) || "Item", x.link, "pj-k")} ${esc(str(x.summary, 120))}<div class="pj-sub">${esc(str(x.status, 40))}`
      + `${rel ? ` · ${esc(rel)}` : ""} · ${owner ? esc(owner) : `<span class="pj-none">no owner</span>`}`
      + `${idle >= 14 ? ` · <span class="pj-idle">idle ${idle} d</span>` : idle ? ` · idle ${idle} d` : ""}</div></li>`;
  };
  const doneRow = x => `<li>${link(str(x.key, 20) || "Item", x.link, "pj-k")} ${esc(str(x.summary, 120))}<div class="pj-sub">Done</div></li>`;
  const movedRow = x => `<li>${link(str(x.key, 20) || "Item", x.link, "pj-k")} ${esc(str(x.summary, 120))}`
    + `<div class="pj-sub">${x.from ? `${esc(str(x.from, 40))} → ` : "Now "}${esc(str(x.to, 40))}</div></li>`;
  const pointRow = o => `<li>${o.mine === true ? `<span class="pj-you">You</span>` : ""}${esc(str(o.text, 200))}`
    + `${o.owner ? `<div class="pj-sub">${esc(str(o.owner, 160))}</div>` : ""}</li>`;
  // A fold that keeps its open/closed state across redraws (data-d names it).
  const fold = (id, title, n, rows, extra) => n ? `<details data-d="${esc(id)}"><summary>${esc(title)} <span class="n">(${n})</span>${extra || ""}</summary><ul>${rows}</ul></details>` : "";

  function card(p, i) {
    const id = `pj-${i}`, rag = RAG[p.rag] ? p.rag : "", trend = TREND[p.trend] ? p.trend : "", base = browseBase(p);
    const st = p.status && typeof p.status === "object" ? p.status : {};
    const meta = [str(p.lead, 80) ? `Lead ${esc(str(p.lead, 80))}` : "", str(st.paf, 40) ? esc(str(st.paf, 40)) : ""].filter(Boolean).join(" · ");
    const att = list(p.attention, 8), next = list(p.next, 8), done = list(p.done, 10), moved = list(p.moved, 8), points = list(p.openPoints, 6);
    const mine = points.filter(o => o.mine === true).length;
    const week = done.length + moved.length;
    const jira = p.jira && typeof p.jira === "object" ? safeUrl(p.jira.link) : "";
    const page = safeUrl(p.page);
    return `<article class="pj-card" aria-labelledby="${id}">`
      + `<div class="pj-top">${rag ? `<span class="pj-rag ${rag}">${RAG[rag]}</span>` : "<span></span>"}${trend ? `<span class="pj-trend ${trend}">${TREND[trend]}</span>` : ""}</div>`
      + `<h3 id="${id}">${link(str(p.name, 120), page)}</h3>`
      + (meta ? `<p class="pj-meta">${meta}</p>` : "")
      + (str(p.why, 300) ? `<p class="pj-why">${withKeys(str(p.why, 300), base)}</p>` : "")
      + deadline(p) + progress(p)
      + (att.length ? `<ul class="pj-atts" aria-label="Needs attention">${att.map(a => attRow(a, base)).join("")}</ul>` : "")
      + fold(`${p.id || i}:next`, "Next up", next.length, next.map(itemRow).join(""))
      + (week ? fold(`${p.id || i}:week`, "Last 7 days", week, done.map(doneRow).join("") + moved.map(movedRow).join(""))
        : `<p class="pj-quiet">Nothing finished or moved in the last 7 days.</p>`)
      + fold(`${p.id || i}:points`, "Open points", points.length, points.map(pointRow).join(""), mine ? ` <span class="pj-you">${mine} yours</span>` : "")
      + ((page || jira) ? `<div class="pj-foot">${page ? link("Project page", page) : ""}${jira ? link("All Jira items", jira) : ""}</div>` : "")
      + `</article>`;
  }

  function drawButton() {
    const ps = projects();
    const n = { red: 0, amber: 0, green: 0 };
    for (const p of ps) if (RAG[p.rag]) n[p.rag]++;
    const worst = n.red ? "red" : n.amber ? "amber" : "green";
    let dot = btn.querySelector(".pj-dot");
    if (!dot) { dot = document.createElement("span"); dot.className = "pj-dot"; dot.setAttribute("aria-hidden", "true"); btn.appendChild(dot); }
    dot.hidden = !(n.red + n.amber + n.green);
    dot.dataset.rag = worst;
    const counts = ["red", "amber", "green"].filter(k => n[k]).map(k => `${n[k]} ${k}`).join(", ");
    const label = counts ? `Projects: ${counts}` : "Projects";
    btn.setAttribute("aria-label", label);
    btn.title = counts ? `${label}. Weekly status of your projects.` : "Projects: weekly status of your projects";
    btn.setAttribute("aria-pressed", String(open));
  }

  function body() {
    if (noStore) return `<p class="pj-empty">Projects need your claude.ai storage. Open Cyberdeck on claude.ai to see them.</p>`;
    if (!loaded) return `<p class="pj-empty">Loading your projects…</p>`;
    const ps = projects();
    if (!status || !ps.length) return `<p class="pj-empty">No project check yet. Every Monday at 07:15 the project agent checks the projects you manage on the PAF Project Organization page in Confluence, with their Jira work, and puts them here.</p>`;
    const order = ps.map((p, i) => [p, i]).sort((a, b) => (RANK[a[0].rag] ?? 3) - (RANK[b[0].rag] ?? 3) || a[1] - b[1]);
    const age = ageDays();
    const notes = (Array.isArray(status.notes) ? status.notes : []).filter(t => typeof t === "string" && t.trim()).slice(0, 4);
    return (age > 8 ? `<p class="pj-stale">This check is ${plural(age, "day")} old. The project agent normally runs every Monday at 07:15; check the scheduled task “Projectagent – weekcheck” on claude.ai.</p>` : "")
      + `<div class="pj-grid">${order.map(([p, i]) => card(p, i)).join("")}</div>`
      + (notes.length ? `<p class="pj-notes">${notes.map(t => esc(t.slice(0, 300))).join(" ")}</p>` : "");
  }

  function draw() {
    drawButton();
    box.hidden = !open;
    if (!open) return;
    const ps = projects(), n = { red: 0, amber: 0, green: 0 };
    for (const p of ps) if (RAG[p.rag]) n[p.rag]++;
    const counts = ps.length ? `<ul class="pj-counts" aria-label="Projects by status">${["red", "amber", "green"].map(k => `<li class="pj-rag ${k}">${n[k]} ${k}</li>`).join("")}</ul>` : "";
    const head = `<div class="pj-head"><h2 class="pj-key" id="projects-title" tabindex="-1">Projects</h2>`
      + `<span class="pj-line">${esc(ps.length ? str(status.headline, 200) : "Your projects, checked every Monday")}</span>`
      + (ps.length && stamp() ? `<span class="pj-stamp">${esc(stamp())}</span>` : "")
      + `<button type="button" class="ghost" data-proj="close">Hide</button></div>`;
    const html = head + counts + body();
    if (html === drawn) return;
    const opened = new Set([...box.querySelectorAll("details[data-d]")].filter(d => d.open).map(d => d.dataset.d));
    box.innerHTML = html;
    drawn = html;
    box.querySelectorAll("details[data-d]").forEach(d => { if (opened.has(d.dataset.d)) d.open = true; });
  }

  btn.addEventListener("click", () => {
    open = !open;
    store.set("ad.projectsOpen", open);
    draw();
    if (!open) return;
    const h = box.querySelector("#projects-title");
    if (h) h.focus({ preventScroll: true });
    const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    box.scrollIntoView({ block: "nearest", behavior: reduce ? "auto" : "smooth" });
  });
  box.addEventListener("click", ev => {
    if (!(ev.target instanceof Element) || !ev.target.closest("[data-proj=close]")) return;
    open = false;
    store.set("ad.projectsOpen", false);
    draw();
    btn.focus();
  });
  setInterval(draw, 3600000); // days left and the age of the check move on
  document.addEventListener("visibilitychange", () => { if (!document.hidden) draw(); });

  // ---------- Settings › Project agent: which page belongs to a project, and extra Jira keys ----------
  const setBox = document.getElementById("projectagent-settings");
  let setRef = null;  // data/users/<you>/projectsettings, once the store is there
  let paSet = {};     // that document as stored; fields this block doesn't know are kept
  let saving = Promise.resolve();
  const PAGE_ID = /^\d{4,}$/, ISSUE = /^[A-Z][A-Z0-9]{1,9}-\d{1,7}$/;
  const pageId = v => { const s = String(v || "").trim(), m = /\/pages\/(\d{4,})/.exec(s); return m ? m[1] : PAGE_ID.test(s) ? s : ""; };
  const mappings = () => list(paSet.mappings, 40).filter(m => typeof m.name === "string" && m.name.trim()).map(m => ({
    name: m.name.trim().slice(0, 80),
    page: PAGE_ID.test(String(m.page || "")) ? String(m.page) : "",
    epics: (Array.isArray(m.epics) ? m.epics : []).filter(k => typeof k === "string" && ISSUE.test(k)).slice(0, 20),
  }));
  const pageUrl = id => {
    const p = projects().find(x => String(x.id) === id);
    return p && safeUrl(p.page) ? safeUrl(p.page) : `https://planon.atlassian.net/wiki/spaces/DEV/pages/${id}`;
  };
  const showErr = t => { const m = setBox && setBox.querySelector("#pa-msg"); if (m) { m.textContent = t; m.hidden = !t; } };
  function renderSettings() {
    if (!setBox || !setRef) return;
    if (!setBox.dataset.ready) {
      setBox.innerHTML = `<h3 id="set-h-projectagent">Project agent</h3>
        <div class="field"><b style="font-size:14px">Project pages</b>
          <p class="hint">Every Monday at 07:15 the project agent checks the projects you manage on the PAF Project Organization page. It finds each project page by its title, "&lt;name&gt; | Project Overview". Link a project here when its page has a different title, or add Jira keys that aren't on the page's roadmap. Kept privately in your claude.ai storage.</p>
          <div class="bday-list" id="pa-list"></div>
          <form class="bday-add" id="pa-add" autocomplete="off">
            <input type="text" id="pa-name" name="name" list="pa-names" maxlength="80" placeholder="Project, as on the PAF page" aria-label="Project name, as on the PAF page">
            <datalist id="pa-names"></datalist>
            <input type="text" id="pa-page" name="page" inputmode="url" spellcheck="false" maxlength="300" placeholder="Page link or id" aria-label="Project page link or page id">
            <input type="text" id="pa-epics" name="epics" spellcheck="false" maxlength="200" placeholder="Extra Jira keys (optional)" aria-label="Extra Jira keys, separated by commas (optional)">
            <button type="submit">Add</button>
          </form>
          <p class="msg err" id="pa-msg" role="alert" hidden></p>
          <p class="hint" id="pa-last"></p></div>`;
      setBox.dataset.ready = "1";
    }
    const rows = mappings().map((m, i) => `<div class="row"><span class="bname">${esc(m.name)}</span><span class="bwhen">`
      + (m.page ? `<a href="${esc(pageUrl(m.page))}" target="_blank" rel="noopener">Page ${esc(m.page)}</a>` : `<span class="hint">Found by title</span>`)
      + (m.epics.length ? `<span class="pj-keys">+ ${esc(m.epics.join(", "))}</span>` : "")
      + `<button type="button" class="ghost" data-padel="${i}" aria-label="Remove the link for ${esc(m.name)}">Remove</button></span></div>`).join("");
    setBox.querySelector("#pa-list").innerHTML = rows || `<p class="hint">No links yet. Projects are found by their page title.</p>`;
    const have = new Set(mappings().map(m => m.name.toLowerCase()));
    setBox.querySelector("#pa-names").innerHTML = projects().map(p => str(p.name, 80)).filter(n => n && !have.has(n.toLowerCase())).map(n => `<option value="${esc(n)}"></option>`).join("");
    const last = setBox.querySelector("#pa-last");
    last.textContent = projects().length ? `Last check: ${stamp()}, ${plural(projects().length, "project")}.` : "No check yet.";
    setBox.hidden = false;
  }
  // Saves the whole document; on failure the store's own copy comes back with the next snapshot.
  function save(next, msg, undoTo) {
    const doc = Object.assign({}, paSet, next, { v: 1, updatedAt: new Date().toISOString() });
    paSet = doc;
    renderSettings();
    saving = saving.then(() => setRef.set(doc)).then(() => {
      showErr("");
      if (msg) say(msg, undoTo ? () => save(undoTo, "Undone") : null);
    }, e => showErr("Couldn't save: " + String((e && (e.message || e.code)) || "unknown error").slice(0, 160)));
    return saving;
  }
  if (setBox) {
    setBox.addEventListener("click", ev => {
      const b = ev.target instanceof Element ? ev.target.closest("[data-padel]") : null;
      if (!b) return;
      const cur = mappings(), i = +b.dataset.padel, gone = cur[i];
      if (!gone) return;
      save({ mappings: cur.filter((_, k) => k !== i) }, `Link for ${gone.name} removed`, { mappings: cur });
      const left = setBox.querySelectorAll("[data-padel]");
      const el = left[Math.min(i, left.length - 1)] || setBox.querySelector("#pa-name");
      if (el) el.focus();
    });
    setBox.addEventListener("submit", ev => {
      const f = ev.target instanceof HTMLFormElement && ev.target.id === "pa-add" ? ev.target : null;
      if (!f) return;
      ev.preventDefault();
      const name = f.elements.namedItem("name").value.trim().slice(0, 80);
      const rawPage = f.elements.namedItem("page").value.trim(), page = pageId(rawPage);
      const keys = f.elements.namedItem("epics").value.split(/[\s,;]+/).map(k => k.trim().toUpperCase()).filter(Boolean);
      if (!name) { showErr("Enter the project name as it is on the PAF page."); f.elements.namedItem("name").focus(); return; }
      if (rawPage && !page) { showErr("Paste the page link from Confluence (…/pages/1234567/…) or just its number."); f.elements.namedItem("page").focus(); return; }
      const bad = keys.filter(k => !ISSUE.test(k));
      if (bad.length) { showErr(`${bad[0]} isn't a Jira key. Use keys like TEC-1234, separated by commas.`); f.elements.namedItem("epics").focus(); return; }
      if (!page && !keys.length) { showErr("Add a page link or at least one Jira key."); f.elements.namedItem("page").focus(); return; }
      const cur = mappings();
      if (cur.some(m => m.name.toLowerCase() === name.toLowerCase())) { showErr(`${name} already has a link. Remove it first to change it.`); return; }
      save({ mappings: cur.concat({ name, page, epics: [...new Set(keys)] }) }, `Link for ${name} saved. The project agent uses it on Monday.`, { mappings: cur });
      f.reset();
      f.elements.namedItem("name").focus();
    });
  }

  if (window.claude && typeof window.claude.use === "function") {
    Promise.all([window.claude.use("db"), window.claude.use("user")]).then(async ([db, user]) => {
      const uid = db && user ? await user.id() : null;
      if (!uid) { noStore = true; loaded = true; draw(); return; }
      db.doc("data/users/" + uid + "/projectstatus").onSnapshot(snap => {
        status = snap.exists ? JSON.parse(JSON.stringify(snap.data() || {})) : null;
        loaded = true;
        draw(); renderSettings();
      }, () => { loaded = true; draw(); });
      setRef = db.doc("data/users/" + uid + "/projectsettings");
      setRef.onSnapshot(snap => {
        if (snap.metadata && snap.metadata.hasPendingWrites) return;
        paSet = snap.exists ? JSON.parse(JSON.stringify(snap.data() || {})) : {};
        renderSettings();
      }, () => {});
      renderSettings();
    }).catch(() => { noStore = true; loaded = true; draw(); });
  } else { noStore = true; loaded = true; }
  draw();
})();
