// Mail & calendar agent: the "Morning briefing" block at the top of Your actions.
// A scheduled Claude task writes one document each weekday at 07:45 to data/users/<you>/agentbriefing
// (format: mail-agenda-agent/briefing-format.md in the repo). The block shows only on the day the briefing is for.
// A plain script like the others; it uses esc, safeUrl, store and now from state.js and keeps everything else to itself.
(() => {
  const box = document.getElementById("agent");
  if (!box) return;
  let brief = null;
  let drawn = "";
  const day = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  const list = (a, n) => Array.isArray(a) ? a.filter(x => x && typeof x === "object").slice(0, n) : [];
  const link = (text, url) => {
    const u = safeUrl(url);
    return u ? `<a href="${esc(u)}" target="_blank" rel="noopener">${esc(text)}</a>` : `<b>${esc(text)}</b>`;
  };
  const mailRow = i => `<li>${link(i.title || "(no subject)", i.link)}${i.from ? ` <span class="meta">· ${esc(i.from)}</span>` : ""}${i.deadline ? ` <span class="due">· ${esc(i.deadline)}</span>` : ""}${i.why ? `<div class="why">${esc(i.why)}</div>` : ""}</li>`;
  function dayCol(d) {
    const issues = list(d.issues, 8).map(x => `<li class="heads">⚠ ${x.link ? link(x.text, x.link) : esc(x.text)}</li>`);
    const meetings = list(d.meetings, 12).map(m => `<li><span class="atime">${esc(m.start || "")}${m.end ? "–" + esc(m.end) : ""}</span>${link(m.title || "(meeting)", m.link)}${m.with ? ` <span class="meta">· ${esc(m.with)}</span>` : ""}${m.note ? `<div class="why">${esc(m.note)}</div>` : ""}</li>`);
    const n = Math.max(0, Math.floor(+d.routine || 0));
    return `<div><h3>${esc(d.label || d.date || "")}</h3>`
      + (issues.length || meetings.length ? `<ul>${issues.join("")}${meetings.join("")}</ul>` : `<p class="quiet">No meetings that need preparing.</p>`)
      + (n ? `<p class="quiet">+ ${n} standup${n === 1 ? "" : "s"} and other routine meetings</p>` : "") + `</div>`;
  }
  function draw() {
    const b = brief;
    if (!b || b.date !== day(now())) { box.hidden = true; return; }
    const folded = store.get("ad.agentFolded", "") === b.date;
    const made = new Date(b.createdAt);
    const stamp = isNaN(made.getTime()) ? "" : made.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    let html = `<div class="ahead"><span class="akey">Morning briefing</span><span class="aline">${esc(b.headline || "")}</span>`
      + (stamp ? `<span class="astamp">${esc(stamp)}</span>` : "")
      + `<button type="button" class="ghost" data-agent="fold" aria-expanded="${!folded}">${folded ? "Show" : "Hide"}</button></div>`;
    if (!folded) {
      const mail = b.mail && typeof b.mail === "object" ? b.mail : {};
      const action = list(mail.action, 12);
      const info = list(mail.info, 30);
      const noise = mail.noise && typeof mail.noise === "object" ? mail.noise : {};
      const groups = list(noise.groups, 8).map(g => `${esc(g.label)} ${Math.max(0, Math.floor(+g.count || 0))}`).join(", ");
      const foot = [];
      const count = Math.max(0, Math.floor(+noise.count || 0));
      if (count) foot.push(`Filtered out ${count} notification${count === 1 ? "" : "s"}${groups ? `: ${groups}` : ""}.`);
      for (const t of (Array.isArray(b.notes) ? b.notes : []).filter(t => typeof t === "string").slice(0, 4)) foot.push(esc(t));
      html += `<div class="acols"><div><h3>Needs you</h3>`
        + (action.length ? `<ul>${action.map(mailRow).join("")}</ul>` : `<p class="quiet">Nothing in your mail needs you right now.</p>`)
        + (info.length ? `<details><summary>For your information (${info.length})</summary><ul>${info.map(mailRow).join("")}</ul></details>` : "")
        + `</div>${list(b.days, 3).map(dayCol).join("")}</div>`
        + (foot.length ? `<p class="afoot">${foot.join(" ")}</p>` : "");
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
  setInterval(draw, 60000); // a new day hides yesterday's briefing
  document.addEventListener("visibilitychange", () => { if (!document.hidden) draw(); });
  if (window.claude && typeof window.claude.use === "function") {
    Promise.all([window.claude.use("db"), window.claude.use("user")]).then(async ([db, user]) => {
      if (!db || !user) return;
      const uid = await user.id();
      if (!uid) return;
      db.doc("data/users/" + uid + "/agentbriefing").onSnapshot(snap => {
        const d = snap.exists ? JSON.parse(JSON.stringify(snap.data() || {})) : null;
        brief = d && typeof d.date === "string" ? d : null;
        draw();
      }, () => { brief = null; draw(); });
    }).catch(() => {});
  }
})();
