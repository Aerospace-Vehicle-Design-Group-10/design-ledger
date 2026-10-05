import json

from conftest import Repo


def seed(repo: Repo):
    repo.set("MTOW", 712000, "N")
    repo.set("MLW", 600000, "N")
    repo.set("fuel_weight", 310000, "N")


def test_publish_records_inputs_and_source(repo):
    seed(repo)
    repo.script("weights/cg.py", """
W0 = ledger.get("MTOW")
Wf = ledger.get("fuel_weight")
ledger.publish("CG_x", 28.4 + 0 * W0 * Wf, units="m")
""")
    out = repo.run("weights/cg.py").stdout
    assert "CG_x = 28.4 m" in out
    rec = repo.params("weights")["CG_x"]
    assert rec["inputs"] == {"MTOW": 712000, "fuel_weight": 310000}
    assert rec["source"]["script"] == "weights/cg.py"
    assert rec["status"] == "computed"
    assert len(rec["source"]["hash"]) == 40

    before = (repo.root / "params/weights.json").read_text()
    out = repo.run("weights/cg.py").stdout
    assert "unchanged" in out
    assert (repo.root / "params/weights.json").read_text() == before


def test_file_that_publishes_is_credited_not_driver(repo):
    seed(repo)
    repo.script("weights/cg.py", """
def go():
    ledger.publish("H", ledger.get("MTOW") / 2, units="N")
""")
    repo.script("run_all.py", "import sys; sys.path.insert(0, 'weights')\nimport cg\ncg.go()\n")
    repo.run("run_all.py")
    assert repo.params("weights")["H"]["source"]["script"] == "weights/cg.py"


def test_step_limits_inputs(repo):
    seed(repo)
    repo.script("weights/two.py", """
a = ledger.get("MLW")
with ledger.step():
    w = ledger.get("MTOW")
    ledger.publish("half", w / 2, units="N")
ledger.publish("both", a + w, units="N")
""")
    repo.run("weights/two.py")
    p = repo.params("weights")
    assert set(p["half"]["inputs"]) == {"MTOW"}
    assert set(p["both"]["inputs"]) == {"MLW", "MTOW"}


def test_explicit_inputs_and_self_excluded(repo):
    seed(repo)
    repo.script("weights/it.py", """
ledger.get("MLW")
w = ledger.get("MTOW")
ledger.publish("MTOW_new", w, units="N", inputs=["MTOW"])
""")
    repo.run("weights/it.py")
    assert set(repo.params("weights")["MTOW_new"]["inputs"]) == {"MTOW"}

    repo.script("weights/iter.py", """
w = ledger.get("MTOW")
ledger.publish("MTOW", w * 0.99, units="N")
""")
    repo.run("weights/iter.py")
    assert "inputs" not in repo.params("requirements")["MTOW"]


def test_override_blocks_publish(repo):
    seed(repo)
    repo.script("weights/whatif.py", """
with ledger.override(MTOW=1.0):
    assert ledger.get("MTOW") == 1.0
    try:
        ledger.publish("X", 1, units="-")
        raise SystemExit("should have failed")
    except ledger.LedgerError:
        pass
assert ledger.get("MTOW") == 712000
""")
    repo.run("weights/whatif.py")


def test_discipline_needed_outside_folders(repo):
    seed(repo)
    repo.script("scratch.py", 'ledger.publish("Y", 1, units="-")\n')
    p = repo.run("scratch.py", check=False)
    assert p.returncode != 0 and "discipline" in p.stderr
    repo.script("scratch2.py", 'ledger.publish("Y", 1, units="-", discipline="wing")\n')
    repo.run("scratch2.py")
    assert "Y" in repo.params("wing")


def test_missing_name_suggests(repo):
    seed(repo)
    repo.script("weights/typo.py", 'ledger.get("MTOV")\n')
    p = repo.run("weights/typo.py", check=False)
    assert "did you mean MTOW" in p.stderr


def test_frozen_blocks_publish_and_unfreeze(repo):
    seed(repo)
    repo.cli("freeze", "poster-v1")
    repo.script("weights/w.py", 'ledger.publish("MTOW", 1.0, units="N")\n')
    p = repo.run("weights/w.py", check=False)
    assert "frozen" in p.stderr
    repo.cli("unfreeze", "MTOW", "--reason", "new engine data")
    repo.run("weights/w.py")
    rec = repo.params("requirements")["MTOW"]
    assert rec["value"] == 1 and rec["unfrozen"]["reason"] == "new engine data"


def chain(repo: Repo):
    seed(repo)
    repo.script("weights/a.py", 'ledger.publish("CG_x", ledger.get("MTOW") / 25000, units="m")\n')
    repo.script("tail/b.py", 'ledger.publish("S_ht", ledger.get("CG_x") * 2, units="m^2")\n')
    repo.script("wing/c.py", 'ledger.publish("trim", ledger.get("S_ht") + ledger.get("MLW") * 0, units="deg")\n')
    for s in ("weights/a.py", "tail/b.py", "wing/c.py"):
        repo.run(s)


def check_json(repo: Repo, *args) -> dict:
    out = repo.root / "r.json"
    repo.cli("check", "--no-lint", "--json", str(out), *args, check=False)
    return json.loads(out.read_text())


def test_all_fresh_after_running(repo):
    chain(repo)
    r = check_json(repo)
    assert r["ok"] and r["counts"]["stale"] == 0 and r["counts"]["upstream"] == 0


def test_stale_and_upstream_and_rerun_order(repo):
    chain(repo)
    repo.set("MTOW", 698500, "N")
    r = check_json(repo)
    assert list(r["stale"]) == ["CG_x"]
    assert "read MTOW=712000, now 698500" in r["stale"]["CG_x"][0]
    assert r["upstream"] == {"S_ht": "CG_x", "trim": "S_ht"}
    assert r["rerun"] == [["weights/a.py"], ["tail/b.py"], ["wing/c.py"]]

    # re-running in order makes everything fresh again
    for s in ("weights/a.py", "tail/b.py", "wing/c.py"):
        repo.run(s)
    r = check_json(repo)
    assert r["counts"]["stale"] == 0 and r["counts"]["upstream"] == 0


def test_same_value_republished_is_not_stale(repo):
    chain(repo)
    repo.set("MTOW", 712000.0, "N")
    assert check_json(repo)["counts"]["stale"] == 0


def test_script_change_is_stale(repo):
    chain(repo)
    p = repo.root / "tail/b.py"
    p.write_text(p.read_text().replace("* 2", "* 2.1"))
    r = check_json(repo)
    assert "has changed" in r["stale"]["S_ht"][0]
    assert r["upstream"] == {"trim": "S_ht"}


def test_crlf_does_not_count_as_change(repo):
    chain(repo)
    p = repo.root / "tail/b.py"
    p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))
    assert check_json(repo)["counts"]["stale"] == 0


def test_converged_loop_is_fresh_and_reported(repo):
    seed(repo)
    repo.set("S", 100, "m^2", "wing")
    repo.script("weights/w.py", 'ledger.publish("W", ledger.get("S") * 10, units="N")\n')
    repo.script("wing/s.py", 'ledger.publish("S", ledger.get("W") / 10, units="m^2")\n')
    repo.run("weights/w.py")
    repo.run("wing/s.py")
    r = check_json(repo)
    assert r["counts"]["stale"] == 0
    assert ["S", "W"] in r["cycles"]


def test_bounds_and_constraints(repo):
    seed(repo)
    repo.set("wing_taper", 1.3, "-", "wing")
    repo.set("MLW", 800000, "N")
    p = repo.cli("check", "--no-lint", check=False)
    assert p.returncode == 1
    assert "outside [0, 1]" in p.stdout
    assert "MLW <= MTOW" in p.stdout and "violated" in p.stdout


def test_schema_errors(repo):
    (repo.root / "params/wing.json").write_text('{"bad name": {"value": 1}}')
    p = repo.cli("check", "--no-lint", check=False)
    assert p.returncode == 1 and "invalid name" in p.stdout and "missing 'units'" in p.stdout
    (repo.root / "params/wing.json").write_text("{nope")
    p = repo.cli("check", "--no-lint", check=False)
    assert "doesn't contain valid json" in p.stdout


def test_lint_finds_hard_coded_numbers(repo):
    seed(repo)
    (repo.root / "weights/bad.py").write_text("W0 = 712000\nx = 0.82\ny = 712000  # ledger: ignore\ng = 9.81\n")
    (repo.root / "wing/bad.m").write_text(
        "W0 = 7.12e5; % from weights\n"
        "s = 'MTOW is 712000';\n"
        "% 712000 in a comment\n"
        "z = x';  w = 712000;\n"
    )
    r = check_json_lint(repo)
    found = sorted(i["subject"] for i in r["items"] if i["code"] == "lint")
    assert found == ["weights/bad.py:1", "wing/bad.m:1", "wing/bad.m:4"]


def test_lint_ignores_a_scripts_own_outputs(repo):
    seed(repo)
    repo.script("wing/choose.py", 'ledger.publish("WS_design", 6123.0, units="N/m^2")\n')
    repo.run("wing/choose.py")
    (repo.root / "tail/uses.py").write_text("ws = 6123.0\n")
    found = sorted(i["subject"] for i in check_json_lint(repo)["items"] if i["code"] == "lint")
    assert found == ["tail/uses.py:1"]


def check_json_lint(repo):
    out = repo.root / "r.json"
    repo.cli("check", "--json", str(out), check=False)
    return json.loads(out.read_text())


def test_show_and_list_and_graph(repo):
    chain(repo)
    repo.set("MTOW", 698500, "N")
    out = repo.cli("show", "CG_x").stdout
    assert "STALE" in out and "← changed" in out and "used by: S_ht" in out
    out = repo.cli("list", "--stale").stdout
    assert "CG_x" in out and "S_ht" in out and "MTOW" not in out.split("\n")[0]
    out = repo.cli("graph", "S_ht").stdout
    assert "CG_x --> S_ht" in out and "MTOW --> CG_x" in out and "class " in out


def test_markdown_report_mentions_owners(repo):
    chain(repo)
    repo.set("MTOW", 698500, "N")
    md = repo.root / "r.md"
    repo.cli("check", "--no-lint", "--md", str(md), "--mention", check=False)
    text = md.read_text()
    assert "<!-- ledger-report -->" in text and "@alice" in text and "Re-run order" in text
