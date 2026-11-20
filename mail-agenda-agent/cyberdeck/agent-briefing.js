// Mail & calendar agent: the "Morning briefing" block at the top of Your actions.
// Two scheduled Claude tasks write to your private store (format: mail-agenda-agent/briefing-format.md in the repo):
// - each weekday at 07:45 the briefing, in data/users/<you>/agentbriefing; shown only on the day it is for;
// - every hour the urgent check, in data/users/<you>/agenturgent; today's alerts show in red at the top, even when folded.
// The briefing can point to reply drafts the agent put in your Outlook Drafts ("Draft ready") and carry a Prep per meeting.
// Its Your team column shows 1:1s that fall behind your rhythm, mail from your people that waits, and your own open promises.
// Settings › Mail agent edits data/users/<you>/agentsettings: your people with their 1:1 rhythm, and the VIPs.
// A plain script like the others; it uses esc, safeUrl, store and now from state.js and keeps everything else to itself.
(() => {
  const box = document.getElementById("agent");
  if (!box) return;
  let brief = null;
  let urgent = null;
  let drawn = "";
  const day = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const hm = iso => { const d = new Date(iso); return isNaN(d.getTime()) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }); };
  const list = (a, n) => Array.isArray(a) ? a.filter(x => x && typeof x === "object").slice(0, n) : [];
  const link = (text, url) => {
    const u = safeUrl(url);
    return u ? `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(text)}</a>` : `<b>${esc(text)}</b>`;
  };
  const draftLink = i => { const u = i.draft && typeof i.draft === "object" ? safeUrl(i.draft.link) : ""; return u ? ` <a class="adraft" href="${esc(u)}" target="_blank" rel="noopener" title="Open the reply draft in Outlook">Draft ready</a>` : ""; };
  const mailRow = i => `<li>${link(i.title || "(no subject)", i.link)}${i.from ? ` <span class="meta">· ${esc(i.from)}</span>` : ""}${i.deadline ? ` <span class="due">· ${esc(i.deadline)}</span>` : ""}${draftLink(i)}${i.why ? `<div class="why">${esc(i.why)}</div>` : ""}${i.draft && typeof i.draft === "object" && typeof i.draft.note === "string" && i.draft.note.trim() ? `<div class="anote">${esc(i.draft.note)}</div>` : ""}</li>`;
  function prepHtml(p) {
    if (!p || typeof p !== "object") return "";
    const mails = list(p.mails, 3).map(x => `<li>${link(x.title || "(no subject)", x.link)}${x.from ? ` <span class="meta">· ${esc(x.from)}</span>` : ""}</li>`);
    const jira = list(p.jira, 3).filter(x => x.key).map(x => `<li>${link(x.key, x.link)}${x.summary ? ` ${esc(x.summary)}` : ""}${x.status ? ` <span class="meta">· ${esc(x.status)}</span>` : ""}</li>`);
    const points = (Array.isArray(p.points) ? p.points : []).filter(t => typeof t === "string" && t.trim()).slice(0, 3).map(t => `<li>${esc(t)}</li>`);
    const goal = typeof p.goal === "string" && p.goal.trim() ? `<p class="why">${esc(p.goal)}</p>` : "";
    if (!goal && !mails.length && !jira.length && !points.length) return "";
    return `<details class="aprep"><summary>Prep</summary>${goal}`
      + (mails.length ? `<h4>Related mail</h4><ul>${mails.join("")}</ul>` : "")
      + (jira.length ? `<h4>Jira</h4><ul>${jira.join("")}</ul>` : "")
      + (points.length ? `<h4>Open points</h4><ul>${points.join("")}</ul>` : "") + `</details>`;
  }
  const alertRow = a => `<li><span class="atag">${a.kind === "vip" ? "VIP" : "Incident"}</span>${link(a.title || "(no subject)", a.link)}`
    + `${a.from ? ` <span class="meta">· ${esc(a.from)}</span>` : ""}${hm(a.when) ? ` <span class="meta">· ${esc(hm(a.when))}</span>` : ""}`
    + `${a.why ? `<div class="why">${esc(a.why)}</div>` : ""}</li>`;
  const RHYTHMS = [[7, "Every week"], [14, "Every 2 weeks"], [21, "Every 3 weeks"], [28, "Every 4 weeks"], [42, "Every 6 weeks"], [0, "No fixed rhythm"]];
  const every = v => Math.max(0, Math.floor(+v || 0));
  const rhythm = n => { const r = RHYTHMS.find(x => x[0] === n); return r ? r[1].toLowerCase() : n ? `every ${n} days` : ""; };
  function teamCol(t) {
    if (!t || typeof t !== "object") return "";
    const ones = list(t.oneOnOnes, 12).filter(x => x.name).map(x => `<li>${link(x.name, x.link)}${every(x.every) ? ` <span class="meta">· 1:1 ${esc(rhythm(every(x.every)))}</span>` : ""}${x.text ? `<div class="why">${esc(x.text)}</div>` : ""}</li>`);
    const waiting = list(t.waiting, 8).map(x => { const n = every(x.days); return `<li>${link(x.title || "(no subject)", x.link)}${x.from ? ` <span class="meta">· ${esc(x.from)}</span>` : ""}${n ? ` <span class="due">· ${n} working day${n === 1 ? "" : "s"}</span>` : ""}</li>`; });
    const promises = list(t.promises, 5).map(x => `<li>${link(x.what || "(promise)", x.link)}${x.to ? ` <span class="meta">· to ${esc(x.to)}</span>` : ""}${x.due ? ` <span class="due">· ${esc(x.due)}</span>` : ""}</li>`);
    const ok = every(t.oneOnOnesOk);
    if (!ones.length && !waiting.length && !promises.length && !ok) return "";
    const okLine = ok ? `<p class="quiet">${ones.length ? `${ok} other 1:1${ok === 1 ? " is" : "s are"}` : `All ${ok} 1:1${ok === 1 ? " is" : "s are"}`} on rhythm.</p>` : "";
    return `<div class="ateam"><h3>Your team</h3>`
      + (ones.length ? `<h4>1:1s</h4><ul>${ones.join("")}</ul>` : "") + okLine
      + (waiting.length ? `<h4>Waiting on your reply</h4><ul>${waiting.join("")}</ul>` : "")
      + (promises.length ? `<h4>Your promises</h4><ul>${promises.join("")}</ul>` : "")
      + (!waiting.length && !promises.length ? `<p class="quiet">No mail from your people waiting on you, and no open promises.</p>` : "") + `</div>`;
  }
  function dayCol(d) {
    const issues = list(d.issues, 8).map(x => `<li class="heads">⚠ ${x.link ? link(x.text, x.link) : esc(x.text)}</li>`);
    const meetings = list(d.meetings, 12).map(m => `<li><span class="atime">${esc(m.start || "")}${m.end ? "–" + esc(m.end) : ""}</span>${link(m.title || "(meeting)", m.link)}${m.with ? ` <span class="meta">· ${esc(m.with)}</span>` : ""}${m.note ? `<div class="why">${esc(m.note)}</div>` : ""}${prepHtml(m.prep)}</li>`);
    const n = Math.max(0, Math.floor(+d.routine || 0));
    return `<div><h3>${esc(d.label || d.date || "")}</h3>`
      + (issues.length || meetings.length ? `<ul>${issues.join("")}${meetings.join("")}</ul>` : `<p class="quiet">No meetings that need preparing.</p>`)
      + (n ? `<p class="quiet">+ ${n} standup${n === 1 ? "" : "s"} and other routine meetings</p>` : "") + `</div>`;
  }
  function draw() {
    const today = day(now());
    const b = brief && brief.date === today ? brief : null;
    const alerts = list(urgent && urgent.alerts, 20).filter(a => a.at && day(new Date(a.at)) === today);
    const checked = urgent && urgent.lastCheck && day(new Date(urgent.lastCheck)) === today ? hm(urgent.lastCheck) : "";
    if (!b && !alerts.length) { box.hidden = true; return; }
    const folded = !!b && store.get("ad.agentFolded", "") === b.date;
    const stamp = b ? hm(b.createdAt) : "";
    let html = `<div class="ahead"><span class="akey">${b ? "Morning briefing" : "Mail agent"}</span><span class="aline">${esc(b ? b.headline || "" : "Urgent mail since this morning's briefing")}</span>`
      + (stamp ? `<span class="astamp">${esc(stamp)}</span>` : "")
      + (b ? `<button type="button" class="ghost" data-agent="fold" aria-expanded="${!folded}">${folded ? "Show" : "Hide"}</button>` : "") + `</div>`;
    if (alerts.length) html += `<div class="aurgent" role="region" aria-label="Urgent mail"><h3>Urgent since the briefing (${alerts.length})</h3><ul>${alerts.map(alertRow).join("")}</ul></div>`;
    if (b && !folded) {
      const mail = b.mail && typeof b.mail === "object" ? b.mail : {};
      const action = list(mail.action, 12);
      const info = list(mail.info, 30);
      const noise = mail.noise && typeof mail.noise === "object" ? mail.noise : {};
      const groups = list(noise.groups, 8).map(g => `${esc(g.label)} ${Math.max(0, Math.floor(+g.count || 0))}`).join(", ");
      const count = Math.max(0, Math.floor(+noise.count || 0));
      const foot = [];
      if (count) foot.push(`Filtered out ${count} notification${count === 1 ? "" : "s"}${groups ? `: ${groups}` : ""}.`);
      for (const t of (Array.isArray(b.notes) ? b.notes : []).filter(t => typeof t === "string").slice(0, 4)) foot.push(esc(t));
      if (checked) foot.push(`Last urgent check ${esc(checked)}.`);
      html += `<div class="acols"><div><h3>Needs you</h3>`
        + (action.length ? `<ul>${action.map(mailRow).join("")}</ul>` : `<p class="quiet">Nothing in your mail needs you right now.</p>`)
        + (info.length ? `<details><summary>For your information (${info.length})</summary><ul>${info.map(mailRow).join("")}</ul></details>` : "")
        + `</div>${list(b.days, 3).map(dayCol).join("")}${teamCol(b.team)}</div>`
        + (foot.length ? `<p class="afoot">${foot.join(" ")}</p>` : "");
    } else if (checked) {
      html += `<p class="afoot">Last urgent check ${esc(checked)}.</p>`;
    }
    if (html !== drawn) {
      const open = [...box.querySelectorAll("details")].map(d => d.open); // keep what you opened open across redraws
      box.innerHTML = html;
      drawn = html;
      box.querySelectorAll("details").forEach((d, k) => { if (open[k]) d.open = true; });
    }
    box.hidden = false;
  }
  box.addEventListener("click", ev => {
    const btn = ev.target instanceof Element ? ev.target.closest("[data-agent=fold]") : null;
    if (!btn || !brief) return;
    store.set("ad.agentFolded", store.get("ad.agentFolded", "") === brief.date ? "" : brief.date);
    draw();
    const again = box.querySelector("[data-agent=fold]");
    if (again) again.focus();
  });
  setInterval(draw, 60000); // a new day hides yesterday's briefing and alerts
  document.addEventListener("visibilitychange", () => { if (!document.hidden) draw(); });

  // ---------- Settings › Mail agent: your people with their 1:1 rhythm, and the VIPs ----------
  const setBox = document.getElementById("agent-settings");
  let setRef = null;  // data/users/<you>/agentsettings, once the store is there
  let agentSet = {};  // that document as stored; fields this block doesn't know are kept
  let saving = Promise.resolve();
  const EMAIL = /^[^\s@<>()",;:[\]]+@[^\s@<>()",;:[\]]+\.[a-z]{2,}$/i;
  const nameOf = e => typeof nameFromEmail === "function" ? nameFromEmail(e) : String(e).split("@")[0];
  const clean = (a, n, withRhythm) => list(a, n).filter(p => typeof p.email === "string" && EMAIL.test(p.email.trim())).map(p => {
    const out = { name: String(p.name || "").trim().slice(0, 80) || nameOf(p.email.trim()), email: p.email.trim() };
    if (withRhythm) out.every = every(p.every);
    return out;
  });
  const people = () => clean(agentSet.people, 60, true);
  const vips = () => clean(agentSet.vips, 30, false);
  const say = (msg, undo) => { if (typeof toast === "function") toast(msg, undo ? { undo } : undefined); };
  const rhythmSelect = (attrs, cur) => `<select ${attrs}>${RHYTHMS.map(([n, l]) => `<option value="${n}"${n === cur ? " selected" : ""}>${l}</option>`).join("")}</select>`;
  const otherDirects = () => {
    if (typeof directReportEmails !== "function") return [];
    const have = new Set(people().map(p => p.email.toLowerCase()));
    return directReportEmails().filter(e => !have.has(e.toLowerCase()));
  };
  function renderSettings() {
    if (!setBox || !setRef) return;
    if (!setBox.dataset.ready) {
      const form = (kind, extra) => `<form class="bday-add" data-agentadd="${kind}" autocomplete="off">
        <input type="text" name="name" maxlength="80" placeholder="Name" aria-label="Name">
        <input type="email" name="email" maxlength="120" placeholder="name@company.com" aria-label="Email address">${extra}
        <button type="submit">Add</button></form>`;
      setBox.innerHTML = `<h3 id="set-h-agent">Mail agent</h3>
        <div class="field"><b style="font-size:14px">Your people and 1:1 rhythm</b>
          <p class="hint">The morning briefing tells you when a 1:1 falls behind this rhythm, and when mail from one of these people has waited two working days for your reply. Kept privately in your claude.ai storage.</p>
          <div class="bday-list" id="agent-people"></div>
          ${form("people", rhythmSelect('name="every" aria-label="1:1 rhythm"', 14))}
          <p class="hint" id="agent-directs" hidden></p></div>
        <div class="field"><b style="font-size:14px">VIPs</b>
          <p class="hint">Mail from these people shows in the hourly urgent check straight away, with a push notification.</p>
          <div class="bday-list" id="agent-vips"></div>
          ${form("vips", "")}</div>
        <p class="msg err" id="agent-set-msg" role="alert" hidden></p>`;
      setBox.dataset.ready = "1";
    }
    const row = (p, i, kind) => `<div class="row"><span class="bname" title="${esc(p.email)}">${esc(p.name)}</span><span class="bwhen">`
      + (kind === "people" ? rhythmSelect(`data-agentevery="${i}" aria-label="1:1 rhythm with ${esc(p.name)}"`, p.every) : "")
      + `<button type="button" class="ghost" data-agentdel="${kind}:${i}" aria-label="Remove ${esc(p.name)}">Remove</button></span></div>`;
    const none = `<p class="hint">Nobody yet.</p>`;
    setBox.querySelector("#agent-people").innerHTML = people().map((p, i) => row(p, i, "people")).join("") || none;
    setBox.querySelector("#agent-vips").innerHTML = vips().map((p, i) => row(p, i, "vips")).join("") || none;
    const n = otherDirects().length, hint = setBox.querySelector("#agent-directs");
    hint.hidden = !n;
    hint.innerHTML = n ? `<button type="button" class="ghost" data-agentdirects>Add your ${n} other direct report${n === 1 ? "" : "s"}</button> from People, without a fixed rhythm.` : "";
    setBox.hidden = false;
  }
  const showErr = t => { const m = setBox && setBox.querySelector("#agent-set-msg"); if (m) { m.textContent = t; m.hidden = !t; } };
  // Saves the whole document; on failure the store's own copy comes back with the next snapshot.
  function save(next, msg, undoTo) {
    const doc = Object.assign({}, agentSet, next, { v: 1, updatedAt: new Date().toISOString() });
    agentSet = doc;
    renderSettings();
    saving = saving.then(() => setRef.set(doc)).then(() => {
      showErr("");
      if (msg) say(msg, undoTo ? () => save(undoTo, "Undone") : null);
    }, e => showErr("Couldn't save: " + String((e && (e.message || e.code)) || "unknown error").slice(0, 160)));
    return saving;
  }
  const focusAfter = (kind, i) => {
    const rows = setBox.querySelectorAll(`[data-agentdel^="${kind}:"]`);
    const el = rows[Math.min(i, rows.length - 1)] || setBox.querySelector(`[data-agentadd="${kind}"] input[name=name]`);
    if (el) el.focus();
  };
  if (setBox) {
    setBox.addEventListener("change", ev => {
      const sel = ev.target instanceof HTMLSelectElement && ev.target.dataset.agentevery !== undefined ? ev.target : null;
      if (!sel) return;
      const prev = { people: people() }, list2 = people(), p = list2[+sel.dataset.agentevery];
      if (!p) return;
      p.every = every(sel.value);
      save({ people: list2 }, `Saved. 1:1 with ${p.name}: ${rhythm(p.every) || "no fixed rhythm"}.`, prev);
    });
    setBox.addEventListener("click", ev => {
      const t = ev.target instanceof Element ? ev.target : null;
      const del = t && t.closest("[data-agentdel]");
      if (del) {
        const [kind, i] = del.dataset.agentdel.split(":"), cur = kind === "vips" ? vips() : people(), gone = cur[+i];
        if (!gone) return;
        save({ [kind]: cur.filter((_, k) => k !== +i) }, `${gone.name} removed from ${kind === "vips" ? "your VIPs" : "your people"}`, { [kind]: cur });
        focusAfter(kind, +i);
        return;
      }
      if (t && t.closest("[data-agentdirects]")) {
        const names = new Map(typeof peopleDirectory === "function" ? peopleDirectory().map(p => [String(p.email).toLowerCase(), p.name]) : []);
        const add = otherDirects().map(e => ({ name: names.get(e.toLowerCase()) || nameOf(e), email: e, every: 0 }));
        if (!add.length) return;
        const prev = people();
        save({ people: prev.concat(add) }, `Added ${add.length} direct report${add.length === 1 ? "" : "s"}. Set a 1:1 rhythm where you want one.`, { people: prev });
        focusAfter("people", prev.length);
      }
    });
    setBox.addEventListener("submit", ev => {
      const f = ev.target instanceof HTMLFormElement ? ev.target : null;
      if (!f || !f.dataset.agentadd) return;
      ev.preventDefault();
      const kind = f.dataset.agentadd, email = f.elements.namedItem("email").value.trim(), name = f.elements.namedItem("name").value.trim();
      if (!EMAIL.test(email)) { showErr("Enter an email address, like name@company.com."); f.elements.namedItem("email").focus(); return; }
      const cur = kind === "vips" ? vips() : people();
      if (cur.some(p => p.email.toLowerCase() === email.toLowerCase())) { showErr(`${email} is already in the list.`); return; }
      const p = { name: name.slice(0, 80) || nameOf(email), email };
      if (kind === "people") p.every = every(f.elements.namedItem("every").value);
      save({ [kind]: cur.concat(p) }, `${p.name} added to ${kind === "vips" ? "your VIPs" : "your people"}`, { [kind]: cur });
      f.reset();
      f.elements.namedItem("name").focus();
    });
    // Direct reports change in Settings › People: keep "Add your other direct reports" up to date.
    const directsChanged = ev => { if (ev.target instanceof Element && ev.target.closest("#set-directs, #directs-suggest, #directs-list")) setTimeout(renderSettings, 0); };
    document.addEventListener("change", directsChanged);
    document.addEventListener("click", directsChanged);
  }

  if (window.claude && typeof window.claude.use === "function") {
    Promise.all([window.claude.use("db"), window.claude.use("user")]).then(async ([db, user]) => {
      if (!db || !user) return;
      const uid = await user.id();
      if (!uid) return;
      const watch = (name, set) => db.doc("data/users/" + uid + "/" + name).onSnapshot(snap => {
        set(snap.exists ? JSON.parse(JSON.stringify(snap.data() || {})) : null);
        draw();
      }, () => { set(null); draw(); });
      watch("agentbriefing", d => { brief = d && typeof d.date === "string" ? d : null; });
      watch("agenturgent", d => { urgent = d && typeof d === "object" ? d : null; });
      setRef = db.doc("data/users/" + uid + "/agentsettings");
      setRef.onSnapshot(snap => {
        if (snap.metadata && snap.metadata.hasPendingWrites) return;
        agentSet = snap.exists ? JSON.parse(JSON.stringify(snap.data() || {})) : {};
        renderSettings();
      }, () => {});
      renderSettings();
    }).catch(() => {});
  }
})();
