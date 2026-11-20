// STEERCO slides: one slide per project in the design of the monthly STEERCO deck ("STEERCO updates November 2026",
// slide 25), filled from the project agent's latest check (the steerco block per project in projectstatus).
// The design is assets/steerco-slide.json, made by project-agent/tools/extract-steerco-template.py: the slide with tokens
// such as {{NAME}}, a template for one status row, the "Decision description" box, and the slide's layout, master and
// theme. The file is built here in the browser with zipFiles and xmlText from office.js; nothing leaves the page.
// A plain script loaded by index.html; all files share one scope, so the order of the script tags matters.

/** @type {Promise<any> | null} */
let steercoTemplate = null;
function loadSteercoTemplate() {
  if (!steercoTemplate) {
    steercoTemplate = fetch("assets/steerco-slide.json").then(r => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); });
    steercoTemplate.catch(() => { steercoTemplate = null; }); // try again next time
  }
  return steercoTemplate;
}

// The status rows top to bottom; CANCELLED only when there is something in it (then six rows, closer together).
const STEERCO_ROWS = ["done", "cancelled", "inProgress", "inTest", "toPickUp", "delayed"];
// Longer texts don't fit their box on the slide.
const STEERCO_MAX = { name: 60, workstream: 50, summary: 90, risk: 200, decision: 150, row: 150, customer: 150, value: 170, point: 100, points: 3, pm: 60 };

/**
 * One project's slide, from its card in projectstatus. @param {any} p the project @param {"green"|"amber"|"red"} rag
 * @param {string} month e.g. "November 2026" @param {string} workstream e.g. "Core Platform"
 */
function steercoSlideData(p, rag, month, workstream) {
  const s = p && typeof p.steerco === "object" && p.steerco ? p.steerco : {};
  const txt = (v, n) => (typeof v === "string" ? v : "").replace(/\s+/g, " ").trim().slice(0, n);
  const prog = s.progress && typeof s.progress === "object" ? s.progress : {};
  const cust = s.customer && typeof s.customer === "object" ? s.customer : {};
  const dec = s.decision && typeof s.decision === "object" ? s.decision : {};
  const att = Array.isArray(p.attention) ? p.attention.find(a => a && (a.level === "red" || a.level === "amber")) : null;
  const who = txt(cust.who, STEERCO_MAX.customer);
  return {
    name: txt(s.title, STEERCO_MAX.name) || txt(p.name, STEERCO_MAX.name),
    workstream: txt(workstream, STEERCO_MAX.workstream) || "Core Platform",
    month,
    summary: txt(s.summary, STEERCO_MAX.summary) || txt(p.why, STEERCO_MAX.summary),
    risk: txt(s.risk, STEERCO_MAX.risk) || (att ? txt(att.text, STEERCO_MAX.risk) : "None."),
    decisionNeeded: dec.needed === true,
    decisionText: txt(dec.text, STEERCO_MAX.decision),
    rows: Object.fromEntries(STEERCO_ROWS.map(k => [k, txt(prog[k], STEERCO_MAX.row)])),
    customer: who ? (/^customer:/i.test(who) ? who : "Customer: " + who) : "",
    value: txt(cust.value, STEERCO_MAX.value),
    points: (Array.isArray(cust.points) ? cust.points : []).map(x => txt(x, STEERCO_MAX.point)).filter(Boolean).slice(0, STEERCO_MAX.points),
    pm: txt(s.manager, STEERCO_MAX.pm),
    rag: rag === "red" || rag === "amber" ? rag : "green",
  };
}

/** The slide's XML: the template with every token filled in. */
function steercoSlideXml(t, d) {
  const T = s => xmlText(String(s ?? ""));
  const fill = (xml, map) => xml.replace(/\{\{([A-Z_]+)\}\}/g, (m, k) => Object.prototype.hasOwnProperty.call(map, k) ? String(map[k]) : m);
  const rows = STEERCO_ROWS.filter(k => k !== "cancelled" || d.rows.cancelled);
  const ys = rows.length > 5 ? t.rows.six : t.rows.five;
  const rowsXml = rows.map((k, n) => fill(t.row, {
    N: n + 1, GID: 1000 + n * 3, LID: 1001 + n * 3, CID: 1002 + n * 3, Y: ys[n],
    LABEL: T(t.labels[k][0]), LABEL_COLOR: t.labels[k][1], TEXT: T(d.rows[k]),
  })).join("");
  let xml = t.slide.replace("<!--ROWS-->", rowsXml)
    .replace("<!--DECISION_TEXT-->", d.decisionNeeded ? fill(t.decision, { DECISION_TEXT: T(d.decisionText || "To be described") }) : "");
  // The customer value points: the paragraph that holds {{POINT}}, once per point.
  const at = xml.indexOf("{{POINT}}");
  if (at >= 0) {
    const start = xml.lastIndexOf("<a:p>", at), end = xml.indexOf("</a:p>", at) + 6;
    const para = xml.slice(start, end);
    xml = xml.slice(0, start) + (d.points.length ? d.points : [""]).map(pt => para.replace("{{POINT}}", T(pt))).join("") + xml.slice(end);
  }
  // Customer value: the sentence and the points move up into the room of an empty box above them.
  const v = t.value, valueY = d.customer ? v.sentenceY : v.customerY;
  const pointsY = d.value ? valueY + (v.pointsY - v.sentenceY) : d.customer ? v.sentenceY : v.customerY;
  return '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + fill(xml, {
    VALUE_Y: valueY, POINTS_Y: pointsY,
    WORKSTREAM: T(d.workstream.toUpperCase()), NAME: T(d.name), RISK: T(d.risk), DECISION: d.decisionNeeded ? "Yes" : "No",
    PM: T(d.pm), MONTH: T(d.month), SUMMARY: T(d.summary), CUSTOMER: T(d.customer), VALUE: T(d.value),
    RAG: d.rag.toUpperCase(), RAG_COLOR: t.rag[d.rag],
  });
}

/** The deck as .pptx bytes: one slide per item of `slides` (from steercoSlideData). */
async function buildSteercoPptx(slides) {
  const t = await loadSteercoTemplate();
  const H = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n';
  const R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships";
  const NSP = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"';
  const rels = list => H + `<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">${list.map(([id, type, target]) => `<Relationship Id="${id}" Type="${R}/${type}" Target="${target}"/>`).join("")}</Relationships>`;
  const ct = "application/vnd.openxmlformats-officedocument.presentationml";
  let masterId = 2147483648; while (t.layoutIds.includes(masterId)) masterId++; // the master's id may not be a layout's
  const files = [
    ["[Content_Types].xml", H + `<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/>`
      + `<Override PartName="/ppt/presentation.xml" ContentType="${ct}.presentation.main+xml"/><Override PartName="/ppt/presProps.xml" ContentType="${ct}.presProps+xml"/>`
      + `<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="${ct}.slideMaster+xml"/><Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="${ct}.slideLayout+xml"/>`
      + `<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>`
      + slides.map((_, k) => `<Override PartName="/ppt/slides/slide${k + 1}.xml" ContentType="${ct}.slide+xml"/>`).join("") + `</Types>`],
    ["_rels/.rels", rels([["rId1", "officeDocument", "ppt/presentation.xml"]])],
    ["ppt/presentation.xml", H + `<p:presentation ${NSP} saveSubsetFonts="1"><p:sldMasterIdLst><p:sldMasterId id="${masterId}" r:id="rId1"/></p:sldMasterIdLst><p:sldIdLst>`
      + slides.map((_, k) => `<p:sldId id="${256 + k}" r:id="rId${10 + k}"/>`).join("")
      + `</p:sldIdLst><p:sldSz cx="${t.size.cx}" cy="${t.size.cy}"/><p:notesSz cx="6858000" cy="9144000"/></p:presentation>`],
    ["ppt/_rels/presentation.xml.rels", rels([["rId1", "slideMaster", "slideMasters/slideMaster1.xml"], ["rId2", "theme", "theme/theme1.xml"], ["rId3", "presProps", "presProps.xml"],
      ...slides.map((_, k) => [`rId${10 + k}`, "slide", `slides/slide${k + 1}.xml`])])],
    ["ppt/presProps.xml", H + `<p:presentationPr ${NSP}/>`],
    ...Object.entries(t.parts),
    ...slides.flatMap((d, k) => [
      [`ppt/slides/slide${k + 1}.xml`, steercoSlideXml(t, d)],
      [`ppt/slides/_rels/slide${k + 1}.xml.rels`, rels([["rId1", "slideLayout", "../slideLayouts/slideLayout1.xml"]])],
    ]),
  ];
  const enc = new TextEncoder();
  return zipFiles(files.map(([name, xml]) => ({ name, data: enc.encode(xml) })));
}
