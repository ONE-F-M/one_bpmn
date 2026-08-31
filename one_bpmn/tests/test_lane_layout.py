"""
Readability guarantees for the swim-lane layout (WI-002042).

A generated lane map has to be reviewable as-is. The old generator chose each
edge's waypoints from its source and target coordinates alone, offsetting
overlapping edges by ``(i % 3) * 10`` — the flow's position in the array — with
no knowledge of any other edge or shape on the canvas. On the real
"TRN – Fuel Requisition" map that produced 544 edge segments running through
shapes they do not connect to and 916 pairs of segments drawn on top of each
other.

buildManualLaneDI now reserves the space between cells — a gutter between
columns, a strip along the bottom of each lane — and every edge travels only
inside them, on a channel allocated by occupancy. These tests measure the DI the
pipeline actually emits and pin the properties that make a map readable:

  * no edge enters a shape it does not connect to
  * no two shapes overlap
  * every shape sits inside the pool, inside exactly one lane band
  * lane bands tile the pool exactly
  * no label lands on another label or on an unrelated shape
  * flow crossings stay at or below the level this work established

The fixture is the recovered IR of a real generated map, so a regression shows up
against the diagram that prompted the story rather than a synthetic one.

Run with:
    pytest one_bpmn/tests/test_lane_layout.py
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

import pytest

PIPELINE_PATH = os.path.normpath(os.path.join(
    os.path.dirname(__file__), "..", "..", "spiff", "pipeline.mjs",
))
FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not os.path.exists(PIPELINE_PATH),
    reason="node or pipeline.mjs unavailable",
)

# Crossings are the one metric a lane layout cannot drive to zero: a re-check
# loop back to an early step has to cross every lane-changing flow it spans, and
# this process has four join gateways collecting such loops. The ceiling locks in
# what the router achieves today (172, down from 228 when edges could only leave
# a shape sideways and loops had only the band beneath the lane to run in); the
# other metrics below are absolute.
MAX_CROSSINGS = 180
# Collinear pairs were short shared approach segments where two arrows reached
# the same node row. There are none left: an edge that arrives vertically now
# docks on the face it is heading for instead of stubbing along the target's row,
# so there is no shared approach to collide on. Held at zero deliberately — a
# pair reappearing means an arrival stub came back.
MAX_COLLINEAR = 0


def run_pipeline(ir: dict) -> str:
    proc = subprocess.run(
        ["node", PIPELINE_PATH],
        input=json.dumps(ir), capture_output=True, text=True, timeout=180,
    )
    assert proc.returncode == 0, f"pipeline exited {proc.returncode}: {proc.stderr[:800]}"
    out = json.loads(proc.stdout)
    assert out.get("ok"), f"pipeline reported problems: {out.get('problems')}"
    return out["xml"]


# ── DI parsing ────────────────────────────────────────────────────────────────

SHAPE_RE = re.compile(
    r'<bpmndi:BPMNShape[^>]*bpmnElement="([^"]+)"[^>]*>\s*'
    r'<dc:Bounds x="([-\d.]+)" y="([-\d.]+)" width="([-\d.]+)" height="([-\d.]+)"'
)
EDGE_RE = re.compile(
    r'<bpmndi:BPMNEdge[^>]*bpmnElement="([^"]+)"[^>]*>(.*?)</bpmndi:BPMNEdge>', re.S
)
WP_RE = re.compile(r'<di:waypoint x="([-\d.]+)" y="([-\d.]+)"')
LABEL_RE = re.compile(
    r'<bpmndi:BPMN(?:Shape|Edge)[^>]*bpmnElement="([^"]+)"(.*?)<bpmndi:BPMNLabel>\s*'
    r'<dc:Bounds x="([-\d.]+)" y="([-\d.]+)" width="([-\d.]+)" height="([-\d.]+)"', re.S
)
FLOW_RE = re.compile(r'<bpmn:sequenceFlow[^>]*id="([^"]+)"[^>]*>')


class Diagram:
    def __init__(self, xml: str):
        self.xml = xml
        self.lane_ids = set(re.findall(r'<bpmn:lane id="([^"]+)"', xml))
        self.shapes = {}
        for m in SHAPE_RE.finditer(xml):
            self.shapes[m.group(1)] = {
                "x": float(m.group(2)), "y": float(m.group(3)),
                "w": float(m.group(4)), "h": float(m.group(5)),
            }
        self.flows = {}
        for m in FLOW_RE.finditer(xml):
            tag = m.group(0)
            src = re.search(r'sourceRef="([^"]+)"', tag)
            tgt = re.search(r'targetRef="([^"]+)"', tag)
            self.flows[m.group(1)] = (
                src.group(1) if src else None,
                tgt.group(1) if tgt else None,
            )
        self.edges = []
        for m in EDGE_RE.finditer(xml):
            pts = [(float(a), float(b)) for a, b in WP_RE.findall(m.group(2))]
            src, tgt = self.flows.get(m.group(1), (None, None))
            self.edges.append({"id": m.group(1), "source": src, "target": tgt, "pts": pts})
        self.labels = [
            {"owner": m.group(1), "x": float(m.group(3)), "y": float(m.group(4)),
             "w": float(m.group(5)), "h": float(m.group(6))}
            for m in LABEL_RE.finditer(xml)
        ]

    @property
    def pool(self):
        return self.shapes["Participant_1"]

    @property
    def lanes(self):
        return {k: v for k, v in self.shapes.items() if k in self.lane_ids}

    @property
    def nodes(self):
        return {k: v for k, v in self.shapes.items()
                if k != "Participant_1" and k not in self.lane_ids}

    def segments(self):
        for e in self.edges:
            for a, b in zip(e["pts"], e["pts"][1:]):
                yield e, a, b


def _boxes_overlap(a, b) -> bool:
    return (a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"]
            and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"])


def _crosses(p, q, r, s) -> bool:
    """True when the two segments intersect at a point interior to both."""
    d = (q[0] - p[0]) * (s[1] - r[1]) - (q[1] - p[1]) * (s[0] - r[0])
    if abs(d) < 1e-9:
        return False
    t = ((r[0] - p[0]) * (s[1] - r[1]) - (r[1] - p[1]) * (s[0] - r[0])) / d
    u = ((r[0] - p[0]) * (q[1] - p[1]) - (r[1] - p[1]) * (q[0] - p[0])) / d
    eps = 1e-6
    return eps < t < 1 - eps and eps < u < 1 - eps


def _intersection(p, q, r, s):
    d = (q[0] - p[0]) * (s[1] - r[1]) - (q[1] - p[1]) * (s[0] - r[0])
    t = ((r[0] - p[0]) * (s[1] - r[1]) - (r[1] - p[1]) * (s[0] - r[0])) / d
    return (p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1]))


def _segment_enters(a, b, rect, pad: float = 2.0) -> bool:
    """Does the segment pass through the interior of rect?"""
    x1, y1 = rect["x"] + pad, rect["y"] + pad
    x2, y2 = rect["x"] + rect["w"] - pad, rect["y"] + rect["h"] - pad
    if x2 <= x1 or y2 <= y1:
        return False
    if abs(a[1] - b[1]) < 1:                                  # horizontal
        return y1 < a[1] < y2 and max(a[0], b[0]) > x1 and min(a[0], b[0]) < x2
    if abs(a[0] - b[0]) < 1:                                  # vertical
        return x1 < a[0] < x2 and max(a[1], b[1]) > y1 and min(a[1], b[1]) < y2
    edges = [((x1, y1), (x2, y1)), ((x2, y1), (x2, y2)),
             ((x2, y2), (x1, y2)), ((x1, y2), (x1, y1))]
    return any(_crosses(a, b, p, q) for p, q in edges)


def _collinear_overlap(a, b, c, d) -> float:
    vert = abs(a[0] - b[0]) < 1 and abs(c[0] - d[0]) < 1 and abs(a[0] - c[0]) < 1
    horiz = abs(a[1] - b[1]) < 1 and abs(c[1] - d[1]) < 1 and abs(a[1] - c[1]) < 1
    if not (vert or horiz):
        return 0.0
    k = 1 if vert else 0
    lo = max(min(a[k], b[k]), min(c[k], d[k]))
    hi = min(max(a[k], b[k]), max(c[k], d[k]))
    return max(0.0, hi - lo)


def metrics(diagram: Diagram) -> dict:
    nodes = diagram.nodes

    through = [
        f"{e['id']} enters {nid}"
        for e, a, b in diagram.segments()
        for nid, rect in nodes.items()
        if nid not in (e["source"], e["target"]) and _segment_enters(a, b, rect)
    ]

    ids = list(nodes)
    shape_overlaps = [
        f"{ids[i]} / {ids[j]}"
        for i in range(len(ids)) for j in range(i + 1, len(ids))
        if _boxes_overlap(nodes[ids[i]], nodes[ids[j]])
    ]

    segs = list(diagram.segments())
    crossings, collinear = [], []
    for i in range(len(segs)):
        ea, a1, a2 = segs[i]
        for j in range(i + 1, len(segs)):
            eb, b1, b2 = segs[j]
            if ea["id"] == eb["id"]:
                continue
            # Flows that meet at a shared node converge there legitimately, but
            # may still cross elsewhere — so only the meeting point is excused.
            shared = [n for n in (ea["source"], ea["target"])
                      if n and n in (eb["source"], eb["target"])]
            if _crosses(a1, a2, b1, b2):
                pt = _intersection(a1, a2, b1, b2)
                at_node = any(
                    nodes[n]["x"] - 12 <= pt[0] <= nodes[n]["x"] + nodes[n]["w"] + 12
                    and nodes[n]["y"] - 12 <= pt[1] <= nodes[n]["y"] + nodes[n]["h"] + 12
                    for n in shared if n in nodes
                )
                if not at_node:
                    crossings.append(f"{ea['id']} x {eb['id']}")
            elif not shared and _collinear_overlap(a1, a2, b1, b2) > 20:
                collinear.append(f"{ea['id']} || {eb['id']}")

    label_clashes = []
    for i, la in enumerate(diagram.labels):
        for lb in diagram.labels[i + 1:]:
            if _boxes_overlap(la, lb):
                label_clashes.append(f"{la['owner']} label / {lb['owner']} label")
    edge_by_id = {e["id"]: e for e in diagram.edges}
    for lab in diagram.labels:
        owner = edge_by_id.get(lab["owner"])
        for nid, rect in nodes.items():
            if nid == lab["owner"]:
                continue
            if owner and nid in (owner["source"], owner["target"]):
                continue
            if _boxes_overlap(lab, rect):
                label_clashes.append(f"{lab['owner']} label on {nid}")

    return {
        "through": through,
        "shape_overlaps": shape_overlaps,
        "crossings": crossings,
        "collinear": collinear,
        "label_clashes": label_clashes,
    }


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def real_map_ir() -> dict:
    with open(os.path.join(FIXTURES, "lane_layout_fuel_requisition_ir.json")) as fh:
        return json.load(fh)


@pytest.fixture(scope="module")
def real_map(real_map_ir) -> Diagram:
    return Diagram(run_pipeline(real_map_ir))


@pytest.fixture(scope="module")
def real_metrics(real_map) -> dict:
    return metrics(real_map)


# ── The guarantees ────────────────────────────────────────────────────────────

def test_no_edge_enters_a_shape_it_does_not_connect_to(real_metrics):
    """Was 544 on this map: every long run was drawn straight from source to
    target coordinates, ploughing through whatever stood between them."""
    assert real_metrics["through"] == [], (
        f"{len(real_metrics['through'])} segments enter unrelated shapes, e.g. "
        f"{real_metrics['through'][:5]}"
    )


def test_no_two_shapes_overlap(real_metrics):
    """One node per (lane, column) cell makes this structural, not incidental."""
    assert real_metrics["shape_overlaps"] == [], real_metrics["shape_overlaps"][:5]


def test_no_label_lands_on_another_label_or_an_unrelated_shape(real_metrics):
    assert real_metrics["label_clashes"] == [], real_metrics["label_clashes"][:5]


def test_segments_are_not_drawn_along_one_another(real_metrics):
    """Was 916 pairs. What remains are short shared approaches into a node."""
    found = real_metrics["collinear"]
    assert len(found) <= MAX_COLLINEAR, f"{len(found)} collinear pairs: {found[:6]}"


def test_flow_crossings_stay_within_budget(real_metrics):
    found = real_metrics["crossings"]
    assert len(found) <= MAX_CROSSINGS, (
        f"{len(found)} avoidable crossings (ceiling {MAX_CROSSINGS}): {found[:6]}"
    )


def test_lane_bands_tile_the_pool_exactly(real_map):
    bands = sorted(real_map.lanes.values(), key=lambda b: b["y"])
    assert bands, "no lane shapes emitted"
    assert bands[0]["y"] == real_map.pool["y"]
    assert sum(b["h"] for b in bands) == real_map.pool["h"]
    for upper, lower in zip(bands, bands[1:]):
        assert upper["y"] + upper["h"] == lower["y"], "gap or overlap between lane bands"


def test_every_node_sits_inside_the_pool_and_one_lane_band(real_map):
    pool, bands = real_map.pool, real_map.lanes
    for nid, n in real_map.nodes.items():
        assert n["x"] >= pool["x"] and n["y"] >= pool["y"], f"{nid} starts outside the pool"
        assert n["x"] + n["w"] <= pool["x"] + pool["w"], f"{nid} overflows the pool"
        assert n["y"] + n["h"] <= pool["y"] + pool["h"], f"{nid} overflows the pool"
        owners = [b for b in bands.values()
                  if n["y"] >= b["y"] and n["y"] + n["h"] <= b["y"] + b["h"]]
        assert len(owners) == 1, f"{nid} is not cleanly inside exactly one lane band"


def test_every_flow_gets_waypoints(real_map):
    missing = [e["id"] for e in real_map.edges if len(e["pts"]) < 2]
    assert missing == [], missing
    assert len(real_map.edges) == len(real_map.flows), "an edge is missing its DI"


def test_diagram_reads_left_to_right(real_map):
    """A lane diagram that grows taller than it is wide has stopped being a flow.
    The old cell-sharing layout stretched this map to 5022px tall."""
    xs = [n["x"] for n in real_map.nodes.values()]
    ys = [n["y"] for n in real_map.nodes.values()]
    assert max(xs) - min(xs) > max(ys) - min(ys)


def test_lane_free_process_is_untouched_by_the_lane_layout(real_map_ir):
    """AC: the flat path must not regress. buildManualLaneDI is only reachable
    when ir.lanes is present, so a lane-free IR never enters this code."""
    flat = json.loads(json.dumps(real_map_ir))
    flat.pop("lanes")
    for node in flat["nodes"]:
        node.pop("lane", None)
    xml = run_pipeline(flat)
    assert "<bpmn:laneSet" not in xml
    assert "bpmnElement=\"Collaboration_1\"" not in xml


def test_channels_are_allocated_by_occupancy_not_by_array_index(real_map):
    """The specific defect this work removed: the old generator offset
    overlapping edges by (i % 3) * 10, so return edges landed in one of three
    channels 10px apart chosen by their position in the flow array. Genuine
    channel allocation shows up as vertical runs sharing an x only when they do
    not overlap in y."""
    verticals = [(a[0], min(a[1], b[1]), max(a[1], b[1]), e["id"])
                 for e, a, b in real_map.segments() if abs(a[0] - b[0]) < 1]
    clashes = [
        (p[3], q[3]) for i, p in enumerate(verticals) for q in verticals[i + 1:]
        if p[3] != q[3] and abs(p[0] - q[0]) < 1
        and min(p[2], q[2]) - max(p[1], q[1]) > 20
    ]
    assert clashes == [], f"{len(clashes)} vertical runs share a channel: {clashes[:5]}"
