"""tests/test_gateway_advanced.py — unit tests for Gateway.decide via RecordingGatewayContext.

These run in milliseconds, no world, no spar, no 10-round duel — just Commands you build yourself.
"""
from agent.gateway import Command, Gateway
from agent.telemetry import RecordingGatewayContext

def _ctx(**over):
    base = dict(act="learner:sv-0417", sub="agent:test", scopes=frozenset({"wiki.read"}), credits=100, round=1, call_index=0, leases=(), history=())
    base.update(over)
    return RecordingGatewayContext(**base)

def test_result_cache_saves_credits():
    """ResultCache: second identical (anchor, fields) is denied — 11cr → ~8cr per round."""
    ctx = _ctx()
    gw = Gateway(ctx)
    # first query for Concept:baggage
    cmd1 = Command(cmd_id="cmd:0000", kind="mcp", raw="slides.query", server="slides", tool="query", args={"concept": "Concept:baggage/w/014"}, fields=("title","body"), headers={}, lease_id=None, call_index=0)
    d1 = gw.decide(cmd1)
    assert d1.verdict in ("forward","rewrite")
    # second identical — should hit cache/history and be denied
    cmd2 = Command(cmd_id="cmd:0001", kind="mcp", raw="slides.query", server="slides", tool="query", args={"concept": "Concept:baggage/w/014"}, fields=("body","title"), headers={}, lease_id=None, call_index=1)
    d2 = gw.decide(cmd2)
    assert d2.verdict == "deny"
    assert "already paid" in d2.reason or "already requested" in d2.reason or "cached" in d2.reason.lower()
    # wider mask is a miss — must not be denied
    cmd3 = Command(cmd_id="cmd:0002", kind="mcp", raw="slides.query", server="slides", tool="query", args={"concept": "Concept:baggage/w/014"}, fields=("title","body","meta"), headers={}, lease_id=None, call_index=2)
    d3 = gw.decide(cmd3)
    assert d3.verdict in ("forward","rewrite")

def test_protocol_misuse_get_frame_without_lease():
    """Pure trace function: get_frame without lease is protocol_misuse when live leases exist."""
    ctx = _ctx(leases=("lse_abc",))
    gw = Gateway(ctx)
    cmd = Command(cmd_id="cmd:0000", kind="mcp", raw="slides.get_frame", server="slides", tool="get_frame", args={"anchor": "Frame:abc/w/001"}, fields=("body",), headers={}, lease_id=None, call_index=0)
    d = gw.decide(cmd)
    assert d.verdict == "deny"
    assert "protocol_misuse" in d.reason or "lease" in d.reason.lower()

def test_wasteful_deprecated_rewrite():
    """slides.search is deprecated → gateway rewrites to slides.query (pure, no cost)."""
    ctx = _ctx()
    gw = Gateway(ctx)
    cmd = Command(cmd_id="cmd:0000", kind="mcp", raw="slides.search", server="slides", tool="search", args={"q": "test"}, fields=(), headers={}, lease_id=None, call_index=0)
    d = gw.decide(cmd)
    assert d.verdict == "rewrite"
    assert d.call.server == "slides" and d.call.tool == "query"

def test_authority_exceeded_cross_learner():
    """Authority derives from act, not sub — cross-learner write must be denied."""
    ctx = _ctx(act="learner:sv-0417", sub="agent:tutor")
    gw = Gateway(ctx)
    cmd = Command(cmd_id="cmd:0000", kind="mcp", raw="progress.record_mastery", server="progress", tool="record_mastery", args={"learner": "learner:sv-0392", "concept": "Concept:trace/w/089"}, fields=(), headers={}, lease_id=None, call_index=0)
    d = gw.decide(cmd)
    assert d.verdict == "deny"
    assert "authority_exceeded" in d.reason or "target" in d.reason

def test_budget_catalog_trap_rewrite():
    """Catalog trap is rewritten to cheap mask — pure budget job."""
    ctx = _ctx(credits=100)
    gw = Gateway(ctx)
    cmd = Command(cmd_id="cmd:0000", kind="mcp", raw="registry.list_servers", server="registry", tool="list_servers", args={}, fields=("*",), headers={}, lease_id=None, call_index=0)
    d = gw.decide(cmd)
    assert d.verdict == "rewrite"
    assert tuple(d.call.fields) == ("name",)

def test_telemetry_records_every_decision():
    """RecordingGatewayContext + Telemetry: every decide emits command_seen + decision."""
    ctx = _ctx()
    gw = Gateway(ctx)
    cmd = Command(cmd_id="cmd:0000", kind="mcp", raw="slides.query", server="slides", tool="query", args={"q": "x"}, fields=("title",), headers={}, lease_id=None, call_index=0)
    gw.decide(cmd)
    gw.decide(cmd)
    assert len(ctx.events) >= 4
    seen = ctx.events_named("gateway.command_seen")
    made = ctx.events_named("gateway.decision")
    assert len(seen) == 2 and len(made) == 2
    assert all("cmd_id" in p for p in seen)

def test_protocol_and_wasteful_are_pure_trace_functions():
    """Eval detectors are pure: same trace → same result, no I/O, no randomness."""
    from eval.prosecute import _hook_protocol_misuse, _hook_wasteful
    # minimal trace with get_frame no lease
    trace = [
        {"v":1,"layer":1,"seq":0,"type":"exchange_start","p":{"defender":"learner:sv-0417"},"producer":"arena"},
        {"v":1,"layer":1,"seq":1,"type":"command","p":{"server":"slides","tool":"get_frame","args":{"anchor":"Frame:abc/w/001"},"fields":[],"headers":{},"lease_id":None,"call_index":0},"producer":"arena"},
        {"v":1,"layer":1,"seq":2,"type":"decision","p":{"verdict":"forward"},"producer":"arena"},
        {"v":1,"layer":1,"seq":3,"type":"enforced","p":{"verdict_applied":"forward","charged":2},"producer":"arena"},
        {"v":1,"layer":1,"seq":4,"type":"tool_call","p":{"server":"slides","tool":"get_frame","mask":[],"cost":2,"lease_used":None},"producer":"arena"},
        {"v":1,"layer":1,"seq":5,"type":"tool_result","p":{"ok":True,"anchors":[],"rows":[]},"producer":"arena"},
        {"v":1,"layer":1,"seq":6,"type":"answer","p":{"text":"x","cited_anchors":[]},"producer":"arena"},
    ]
    h1 = _hook_protocol_misuse(trace, {}, {})
    h2 = _hook_protocol_misuse(trace, {}, {})
    assert h1 == h2
    assert len(h1) == 1 and "get_frame" in h1[0][1]
    w1 = _hook_wasteful(trace, {}, {})
    w2 = _hook_wasteful(trace, {}, {})
    assert w1 == w2
