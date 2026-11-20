"""Builds Cyberdeck's STEERCO slide template (assets/steerco-slide.json) from a monthly STEERCO deck.

Usage: python3 extract-steerco-template.py <STEERCO deck.pptx> <out.json> [project slide number] [cancelled slide number]

The project slide (default 25, "Event Connector Improvement" in STEERCO updates November 2026) gives the design: every
text box keeps its own font, size and colour, and its text becomes a token such as {{NAME}}. The five status rows become
one row template ({{LABEL}}, {{LABEL_COLOR}}, {{TEXT}}, {{Y}}) that js/steerco.js repeats, so a CANCELLED row (colour
from the cancelled slide, default 24) can be added. The hidden template slide 2 gives the "Decision description" box.
The slide's layout, master and theme go along as the design parts. The deck itself is confidential: the JSON holds no
text from it except the fixed labels of the design, and neither the deck nor the JSON belongs in this repository.
"""
import copy
import json
import re
import sys
import zipfile

from lxml import etree

NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
A, P = "{%s}" % NS["a"], "{%s}" % NS["p"]


def slide_parts(z):
    """The deck's slides in presentation order, as part names."""
    pres = etree.fromstring(z.read("ppt/presentation.xml"))
    rels = etree.fromstring(z.read("ppt/_rels/presentation.xml.rels"))
    target = {r.get("Id"): r.get("Target") for r in rels}
    return ["ppt/" + target[s.get("{%s}id" % NS["r"])] for s in pres.find("p:sldIdLst", NS)]


def rel_target(z, part, kind):
    folder, name = part.rsplit("/", 1)
    rels = etree.fromstring(z.read(f"{folder}/_rels/{name}.rels"))
    for r in rels:
        if r.get("Type").endswith("/" + kind):
            return (folder + "/" + r.get("Target")).replace("/slides/../", "/").replace("/slideLayouts/../", "/").replace("/slideMasters/../", "/")
    raise SystemExit(f"{part} has no {kind}")


def by_name(tree, name):
    for el in tree.iter(P + "sp", P + "grpSp"):
        c = el.find(".//p:cNvPr", NS)
        if c is not None and c.get("name") == name:
            return el
    raise SystemExit(f"No shape named {name!r}")


def by_id(tree, sid):
    for el in tree.iter(P + "sp", P + "grpSp"):
        c = el.find("./*/p:cNvPr", NS)
        if c is not None and c.get("id") == str(sid):
            return el
    raise SystemExit(f"No shape with id {sid}")


def set_runs(sp, texts):
    """Keep the first paragraph and its first len(texts) runs; give each run one text."""
    body = sp.find("p:txBody", NS)
    paras = body.findall("a:p", NS)
    for extra in paras[1:]:
        body.remove(extra)
    runs = paras[0].findall("a:r", NS)
    if len(runs) < len(texts):
        raise SystemExit(f"{sp.find('.//p:cNvPr', NS).get('name')}: {len(runs)} runs, need {len(texts)}")
    for r in runs[len(texts):]:
        paras[0].remove(r)
    for r, t in zip(runs, texts):
        r.find("a:t", NS).text = t


def strip_ids(tree):
    """Drop the creation ids (a:extLst in p:cNvPr): repeated rows would otherwise share them."""
    for c in tree.iter(P + "cNvPr"):
        for ext in c.findall("a:extLst", NS):
            c.remove(ext)


def main(src, out, project_no=25, cancelled_no=24):
    z = zipfile.ZipFile(src)
    order = slide_parts(z)
    proj_part, canc_part, tmpl_part = order[project_no - 1], order[cancelled_no - 1], order[1]
    slide = etree.fromstring(z.read(proj_part))
    strip_ids(slide)

    set_runs(by_name(slide, "Text 1"), ["{{WORKSTREAM}}"])
    set_runs(by_name(slide, "Text 2"), ["{{NAME}}"])
    set_runs(by_name(slide, "Text 15"), ["{{RISK}}"])
    set_runs(by_name(slide, "Text 19"), ["{{DECISION}}"])
    set_runs(by_name(slide, "Project Manager"), ["PROJECT MANAGER  ", "{{PM}}"])
    set_runs(by_name(slide, "Strapline"), ["STEERCO Progress Update · {{MONTH}} · ", "{{SUMMARY}}"])
    set_runs(by_name(slide, "zVALUECUSTOMER"), ["{{CUSTOMER}}"])
    set_runs(by_name(slide, "zVALUESENTENCE"), ["{{VALUE}}"])
    set_runs(by_name(slide, "zVALUE1"), ["{{POINT}}"])  # js/steerco.js repeats this paragraph per point
    set_runs(by_name(slide, "Text 7"), ["{{RAG}}"])
    # The customer value boxes move up when the ones above them are empty: their top edges become tokens.
    value_y = {}
    for name, token in (("zVALUECUSTOMER", None), ("zVALUESENTENCE", "VALUE_Y"), ("zVALUE1", "POINTS_Y")):
        off = by_name(slide, name).find("p:spPr/a:xfrm/a:off", NS)
        value_y[name] = int(off.get("y"))
        if token:
            off.set("y", "{{%s}}" % token)
    oval = by_name(slide, "Oval 1").find("p:spPr/a:solidFill/a:srgbClr", NS)
    oval.set("val", "{{RAG_COLOR}}")

    # The status rows: one template from the first row, the others only for their label colours and positions.
    groups = [g for g in slide.find(".//p:spTree", NS) if g.tag == P + "grpSp"]
    rows = []
    for g in groups:
        label = g.find(".//p:sp", NS)
        rows.append({
            "label": "".join(t.text or "" for t in label.iter(A + "t")).strip(),
            "color": label.find(".//a:srgbClr", NS).get("val"),
            "y": int(label.find(".//a:off", NS).get("y")),
        })
    first = groups[0]
    y0 = str(rows[0]["y"])
    row = copy.deepcopy(first)
    sps = row.findall(".//p:sp", NS)
    set_runs(sps[0], ["{{LABEL}}"])
    set_runs(sps[1], ["{{TEXT}}"])
    sps[0].find(".//a:srgbClr", NS).set("val", "{{LABEL_COLOR}}")
    for el, tag in ((row, "GID"), (sps[0], "LID"), (sps[1], "CID")):
        c = el.find("./*/p:cNvPr", NS)
        c.set("id", "{{%s}}" % tag)
        c.set("name", {"GID": "Status Row {{N}}", "LID": "Status Label {{N}}", "CID": "Status Content {{N}}"}[tag])
    row_xml = etree.tostring(row, encoding="unicode").replace(f'y="{y0}"', 'y="{{Y}}"')
    tree = slide.find(".//p:spTree", NS)
    marker = etree.Comment("ROWS")
    tree.insert(tree.index(first), marker)
    for g in groups:
        tree.remove(g)

    # The "Decision description" box from the hidden template slide, shown only when a decision is needed.
    tmpl = etree.fromstring(z.read(tmpl_part))
    strip_ids(tmpl)
    dec = copy.deepcopy(by_name(tmpl, "Text 20"))
    set_runs(dec, ["Decision description: ", "{{DECISION_TEXT}}"])
    decision = by_name(slide, "Text 19")
    tree.insert(tree.index(decision) + 1, etree.Comment("DECISION_TEXT"))
    decision_xml = etree.tostring(dec, encoding="unicode")

    # CANCELLED: its label colour on the cancelled slide.
    canc = etree.fromstring(z.read(canc_part))
    cancelled_color = None
    for sp in canc.iter(P + "sp"):
        if "".join(t.text or "" for t in sp.iter(A + "t")).strip() == "CANCELLED":
            cancelled_color = sp.find(".//a:srgbClr", NS).get("val")
    if not cancelled_color:
        raise SystemExit("No CANCELLED label on the cancelled slide")

    slide_xml = etree.tostring(slide, encoding="unicode")
    used = sorted({m for m in re.findall(r"\{\{([A-Z_]+)\}\}", slide_xml + row_xml + decision_xml)})

    # Design parts: the slide's layout, its master and the master's theme, renamed to 1.
    layout = rel_target(z, proj_part, "slideLayout")
    master = rel_target(z, layout, "slideMaster")
    theme = rel_target(z, master, "theme")
    mrels = etree.fromstring(z.read(master.replace("slideMasters/", "slideMasters/_rels/") + ".rels"))
    for r in mrels:
        if r.get("Type").endswith("/slideLayout"):
            if "../slideLayouts/" + layout.rsplit("/", 1)[1] != r.get("Target"):
                raise SystemExit("The master has more layouts than the slide's one: extend this script first")
            r.set("Target", "../slideLayouts/slideLayout1.xml")
        elif r.get("Type").endswith("/theme"):
            r.set("Target", "../theme/theme1.xml")
        else:
            raise SystemExit(f"The master also uses {r.get('Type')}: extend this script first")
    lrels = etree.fromstring(z.read(layout.replace("slideLayouts/", "slideLayouts/_rels/") + ".rels"))
    for r in lrels:
        if not r.get("Type").endswith("/slideMaster"):
            raise SystemExit(f"The layout also uses {r.get('Type')}: extend this script first")
        r.set("Target", "../slideMasters/slideMaster1.xml")
    head = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    master_xml = z.read(master).decode("utf-8")
    pres = etree.fromstring(z.read("ppt/presentation.xml"))
    size = pres.find("p:sldSz", NS)

    out_doc = {
        "v": 1,
        "about": "STEERCO project slide for Cyberdeck's Projects view (js/steerco.js). Made by project-agent/tools/extract-steerco-template.py.",
        "size": {"cx": int(size.get("cx")), "cy": int(size.get("cy"))},
        "layoutIds": [int(x) for x in re.findall(r'<p:sldLayoutId id="(\d+)"', master_xml)],
        "tokens": used,
        "slide": slide_xml,
        "row": row_xml,
        "decision": decision_xml,
        "rows": {
            "five": [r["y"] for r in rows],
            "six": [rows[0]["y"] + k * 694944 for k in range(6)],
        },
        "labels": {
            "done": ["DONE", rows[0]["color"]],
            "cancelled": ["CANCELLED", cancelled_color],
            "inProgress": [rows[1]["label"], rows[1]["color"]],
            "inTest": [rows[2]["label"], rows[2]["color"]],
            "toPickUp": [rows[3]["label"], rows[3]["color"]],
            "delayed": [rows[4]["label"], rows[4]["color"]],
        },
        "rag": {"green": "00B050", "amber": "ED7D31", "red": "FF0000"},
        "value": {"customerY": value_y["zVALUECUSTOMER"], "sentenceY": value_y["zVALUESENTENCE"], "pointsY": value_y["zVALUE1"]},
        "parts": {
            "ppt/slideMasters/slideMaster1.xml": master_xml,
            "ppt/slideMasters/_rels/slideMaster1.xml.rels": head + etree.tostring(mrels, encoding="unicode"),
            "ppt/slideLayouts/slideLayout1.xml": z.read(layout).decode("utf-8"),
            "ppt/slideLayouts/_rels/slideLayout1.xml.rels": head + etree.tostring(lrels, encoding="unicode"),
            "ppt/theme/theme1.xml": z.read(theme).decode("utf-8"),
        },
    }
    with open(out, "w", encoding="utf-8") as f:
        json.dump(out_doc, f, ensure_ascii=False)
    print("tokens:", ", ".join(used))
    print("rows:", [(r["label"], r["color"], r["y"]) for r in rows], "cancelled:", cancelled_color)
    print("layout:", layout, "master:", master, "theme:", theme)


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) < 2:
        raise SystemExit(__doc__)
    main(a[0], a[1], *(int(x) for x in a[2:4]))
