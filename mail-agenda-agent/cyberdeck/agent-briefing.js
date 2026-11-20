// Mail & calendar agent: the "Morning briefing" block at the top of Your actions.
// Two scheduled Claude tasks write to your private store (format: mail-agenda-agent/briefing-format.md in the repo):
// - each weekday at 07:45 the briefing, in data/users/<you>/agentbriefing; shown only on the day it is for;
// - every hour the urgent check, in data/users/<you>/agenturgent; today's alerts show in red at the top, even when folded.
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
  const mailRow = i => `<li>${link(i.title || "(no subject)", i.link)}${i.from ? ` <span class="meta">· ${esc(i.from)}</span>` : ""}${i.deadline ? ` <span class="due">· ${esc(i.deadline)}</span>` : ""}${i.why ? `<div class="why">${esc(i.why)}</div>` : ""}</li>`;
  const alertRow = a => `<li><span class="atag">${a.kind === "vip" ? "VIP" : "Incident"}</span>${link(a.title || "(no subject)", a.link)}`
    + `${a.from ? ` <span class="meta">· ${esc(a.from)}</span>` : ""}${hm(a.when) ? ` <span class="meta">· ${esc(hm(a.when))}</span>` : ""}`
    + `${a.why ? `<div class="why">${esc(a.why)}</div>` : ""}</li>`;
  function dayCol(d) {
    const issues = list(d.issues, 8).map(x => `<li class="heads">⚠ ${x.link ? link(x.text, x.link) : esc(x.text)}</li>`);
    const meetings = list(d.meetings, 12).map(m => `<li><span class="atime">${esc(m.start || "")}${m.end ? "–" + esc(m.end) : ""}</span>${link(m.title || "(meeting)", m.link)}${m.with ? ` <span class="meta">· ${esc(m.with)}</span>` : ""}${m.note ? `<div class="why">${esc(m.note)}</div>` : ""}</li>`);
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
        + `</div>${list(b.days, 3).map(dayCol).join("")}</div>`
        + (foot.length ? `<p class="afoot">${foot.join(" ")}</p>` : "");
    } else if (checked) {
      html += `<p class="afoot">Last urgent check ${esc(checked)}.</p>`;
    }
    if (html !== drawn) {
      const open = box.querySelector("details[open]") !== null; // keep "For your information" open across redraws
      box.innerHTML = html;
      drawn = html;
      if (open) { const det = box.querySelector("details"); if (det) det.open = true; }
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
    }).catch(() => {});
  }
})();
