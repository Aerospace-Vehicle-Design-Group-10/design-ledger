"""`reference`: where a hand-entered number came from. Required (CI error) for statuses in
`require_reference` (default: assumed only)."""
import json

from conftest import Repo


def check(repo: Repo):
    out = repo.root / "r.json"
    p = repo.cli("check", "--no-lint", "--json", str(out), check=False)
    return p, json.loads(out.read_text())


def missing(rep: dict) -> list[str]:
    return sorted(i["subject"] for i in rep["items"] if i["code"] == "reference")


def test_hand_entered_value_without_reference_fails(repo):
    out = repo.cli("set", "LD_cruise", "17", "--units", "-", "--discipline", "weights").stdout
    assert "has no reference, so CI will fail" in out
    p, rep = check(repo)
    assert p.returncode == 1 and missing(rep) == ["LD_cruise"]
    assert "ledger cite" in p.stdout


def test_set_with_reference_passes_and_is_shown(repo):
    repo.set("n_pax", 150, reference="AVD brief 2026-27, §2.1")
    p, rep = check(repo)
    assert p.returncode == 0 and missing(rep) == []
    assert repo.params("requirements")["n_pax"]["reference"] == "AVD brief 2026-27, §2.1"
    assert "reference: AVD brief 2026-27, §2.1" in repo.cli("show", "n_pax").stdout


def test_cite_adds_reference_without_touching_value_even_when_frozen(repo):
    repo.set("n_pax", 150, reference=None)
    repo.set("cargo_mass", 40000, "kg", reference=None)
    repo.cli("freeze", "brief")
    before = repo.params("requirements")
    repo.cli("cite", "AVD brief 2026-27, §2.1", "n_pax", "cargo_mass")
    after = repo.params("requirements")
    for n in ("n_pax", "cargo_mass"):
        assert after[n]["reference"] == "AVD brief 2026-27, §2.1"
        assert after[n]["value"] == before[n]["value"] and after[n]["updated"] == before[n]["updated"]
        assert after[n]["frozen"] == "brief"
    assert check(repo)[0].returncode == 0


def test_cite_unknown_name_changes_nothing(repo):
    repo.set("n_pax", 150, reference=None)
    p = repo.cli("cite", "x", "n_pax", "nope", check=False)
    assert p.returncode != 0 and "'nope' isn't in the registry" in p.stderr
    assert "reference" not in repo.params("requirements")["n_pax"]


def test_requirements_dont_need_one_by_default(repo):
    repo.cli("set", "n_pax", "150", "--units", "-", "--discipline", "requirements", "--requirement")
    assert missing(check(repo)[1]) == []


def test_computed_values_dont_need_one(repo):
    repo.set("MTOW", 712000, "N")
    repo.script("weights/w.py", 'ledger.publish("W", ledger.get("MTOW") / 2, units="N")\n')
    repo.run("weights/w.py")
    assert missing(check(repo)[1]) == []


def test_script_publishing_constants_counts_as_assumed(repo):
    repo.script("weights/choose.py", 'ledger.publish("WS_design", 6250.0, units="N/m^2")\n')
    repo.run("weights/choose.py")
    assert missing(check(repo)[1]) == ["WS_design"]
    repo.script("weights/choose.py",
                'ledger.publish("WS_design", 6250.0, units="N/m^2", reference="constraint diagram, poster fig. 3")\n')
    repo.run("weights/choose.py")
    assert missing(check(repo)[1]) == []


def test_reference_survives_republish_and_can_be_replaced(repo):
    repo.set("LD_cruise", 17, reference="Raymer Fig. 3.6")
    repo.cli("set", "LD_cruise", "18", "--units", "-")              # no --reference given
    assert repo.params("requirements")["LD_cruise"]["reference"] == "Raymer Fig. 3.6"
    repo.cli("set", "LD_cruise", "18", "--units", "-", "--reference", "drag build-up v2")
    assert repo.params("requirements")["LD_cruise"]["reference"] == "drag build-up v2"


def test_empty_reference_is_a_schema_error(repo):
    repo.set("n_pax", 150)
    f = repo.root / "params/requirements.json"
    f.write_text(f.read_text().replace('"reference": "test fixture"', '"reference": "  "'))
    p, rep = check(repo)
    assert p.returncode == 1 and any("non-empty text" in i["message"] for i in rep["items"])


def test_rule_is_configurable(repo):
    cfg = json.loads((repo.root / "ledger.json").read_text())
    cfg["require_reference"] = ["requirement"]
    (repo.root / "ledger.json").write_text(json.dumps(cfg))
    repo.cli("set", "LD_cruise", "17", "--units", "-", "--discipline", "weights")      # assumed
    assert check(repo)[0].returncode == 0
