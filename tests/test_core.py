import json

from ledger import jsonfmt, merge
from ledger.check import eval_constraint, tarjan
from ledger.lint import sig_figs


# ------------------------------------------------------------------ formatting
def test_numbers_canonical():
    assert jsonfmt.fmt_number(712000.0) == "712000"
    assert jsonfmt.fmt_number(712000) == "712000"
    assert jsonfmt.fmt_number(0.1) == "0.1"
    assert jsonfmt.fmt_number(1 / 3) == "0.3333333333333333"
    assert jsonfmt.fmt_number(1e-5) == "1e-05"
    assert jsonfmt.fmt_number(True) == "true"


def test_record_field_order_and_flat_lists():
    txt = jsonfmt.dumps({"X": {"updated": "t", "value": [1, 2], "by": "me", "units": "m", "status": "assumed"}})
    keys = [l.split(":")[0].strip().strip('"') for l in txt.splitlines()[2:7]]
    assert keys == ["value", "units", "status", "by", "updated"]
    assert '"value": [1, 2]' in txt
    assert json.loads(txt)["X"]["value"] == [1, 2]


# ------------------------------------------------------------------ helpers
def test_sig_figs():
    assert sig_figs("712000") == 3
    assert sig_figs("0.82") == 2
    assert sig_figs("24.1") == 3
    assert sig_figs("3.75") == 3
    assert sig_figs("1.20") == 3
    assert sig_figs("7.12e5") == 3
    assert sig_figs("100") == 1


def test_constraints():
    v = {"MLW": 5, "MTOW": 10}
    assert eval_constraint("MLW <= MTOW", v) is True
    assert eval_constraint("MLW > MTOW", v) is False
    assert eval_constraint("MLW + 6 <= MTOW", v) is False
    assert eval_constraint("MLW < OEW", v) is None
    assert eval_constraint("0 < MLW < MTOW", v) is True


def test_tarjan_orders_dependencies_first():
    # c needs b, b needs a; x <-> y loop
    comps = tarjan(["a", "b", "c", "x", "y"], {"c": {"b"}, "b": {"a"}, "x": {"y"}, "y": {"x"}})
    order = [c for c in comps if len(c) == 1]
    assert order.index(["a"]) < order.index(["b"]) < order.index(["c"])
    assert ["x", "y"] in comps


# ------------------------------------------------------------------ merge driver
def test_merge_disjoint_and_conflict():
    base = {"A": {"value": 1}}
    ours = {"A": {"value": 1}, "B": {"value": 2}}
    theirs = {"A": {"value": 1}, "C": {"value": 3}}
    m, c = merge.merge(base, ours, theirs)
    assert set(m) == {"A", "B", "C"} and not c

    m, c = merge.merge(base, {"A": {"value": 5}}, {"A": {"value": 1}})
    assert m["A"]["value"] == 5 and not c

    m, c = merge.merge(base, {"A": {"value": 5}}, {"A": {"value": 6}})
    assert c == ["A"]

    m, c = merge.merge(base, {}, base)          # deleted on our side
    assert "A" not in m and not c
