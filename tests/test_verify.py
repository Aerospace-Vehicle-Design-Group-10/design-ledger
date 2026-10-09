"""`verified`: "-" until a person runs `ledger verify`; tied to the value that was checked."""
import json

from conftest import Repo, git


def seed(repo: Repo):
    repo.set("MTOW", 712000, "N")
    repo.set("n_pax", 150, "-")


def check_json(repo: Repo, *args) -> dict:
    out = repo.root / "r.json"
    repo.cli("check", "--no-lint", "--json", str(out), *args, check=False)
    return json.loads(out.read_text())


def test_new_values_are_unverified(repo):
    seed(repo)
    assert repo.params("requirements")["MTOW"]["verified"] == "-"
    assert check_json(repo)["counts"]["verified"] == 0


def test_verify_records_who_what_and_how(repo):
    seed(repo)
    out = repo.cli("verify", "MTOW", "n_pax", "--note", "brief 2.1").stdout
    assert "Verified MTOW = 712000 N" in out
    v = repo.params("requirements")["MTOW"]["verified"]
    assert v["value"] == 712000 and v["units"] == "N" and v["note"] == "brief 2.1" and v["by"] and v["at"]
    assert check_json(repo)["counts"]["verified"] == 2
    assert "✓" in repo.cli("list").stdout
    assert "verified by" in repo.cli("show", "MTOW").stdout
    assert "MTOW" not in repo.cli("list", "--unverified").stdout


def test_same_value_keeps_verification_new_value_clears_it(repo):
    seed(repo)
    repo.cli("verify", "MTOW")
    repo.set("MTOW", 712000.0, "N")                     # same number
    assert isinstance(repo.params("requirements")["MTOW"]["verified"], dict)
    out = repo.cli("set", "MTOW", "700000", "--units", "N", "--discipline", "requirements").stdout
    assert "verification cleared" in out
    assert repo.params("requirements")["MTOW"]["verified"] == "-"


def test_units_change_clears_verification(repo):
    seed(repo)
    repo.cli("verify", "MTOW")
    repo.set("MTOW", 712000, "kN")
    assert repo.params("requirements")["MTOW"]["verified"] == "-"


def test_rerun_with_same_output_keeps_verification(repo):
    seed(repo)
    repo.script("weights/w.py", 'ledger.publish("W", ledger.get("MTOW") / 2, units="N")\n')
    repo.run("weights/w.py")
    repo.cli("verify", "W")
    p = repo.root / "weights/w.py"
    p.write_text(p.read_text() + "# reworded comment\n")
    repo.run("weights/w.py")                            # script changed, value identical
    assert isinstance(repo.params("weights")["W"]["verified"], dict)


def test_cannot_verify_a_stale_value_without_force(repo):
    seed(repo)
    repo.script("weights/w.py", 'ledger.publish("W", ledger.get("MTOW") / 2, units="N")\n')
    repo.run("weights/w.py")
    repo.set("MTOW", 700000, "N")
    p = repo.cli("verify", "W", "n_pax", check=False)
    assert p.returncode != 0 and "stale" in p.stderr
    assert repo.params("requirements")["n_pax"]["verified"] == "-"     # nothing half-done
    repo.cli("verify", "W", "--force")
    assert isinstance(repo.params("weights")["W"]["verified"], dict)


def test_hand_edited_value_flags_outdated_verification(repo):
    seed(repo)
    repo.cli("verify", "MTOW")
    f = repo.root / "params/requirements.json"
    f.write_text(f.read_text().replace('"value": 712000,', '"value": 700000,', 1))
    r = check_json(repo)
    items = [i for i in r["items"] if i["code"] == "verified"]
    assert items and "it's now 700000" in items[0]["message"]
    assert r["counts"]["verified"] == 0
    assert "OUTDATED" in repo.cli("show", "MTOW").stdout


def test_unverify(repo):
    seed(repo)
    repo.cli("verify", "MTOW")
    repo.cli("unverify", "MTOW")
    assert repo.params("requirements")["MTOW"]["verified"] == "-"


def test_malformed_verified_is_a_schema_error(repo):
    seed(repo)
    f = repo.root / "params/requirements.json"
    f.write_text(f.read_text().replace('"verified": "-"', '"verified": "yes"', 1))
    p = repo.cli("check", "--no-lint", check=False)
    assert p.returncode == 1 and "'verified' must be" in p.stdout


def test_verifying_a_frozen_value_is_allowed_and_ci_shows_it(repo):
    seed(repo)
    git(repo.root, "init", "-q", "-b", "main")
    git(repo.root, "config", "user.name", "T")
    git(repo.root, "config", "user.email", "t@example.com")
    repo.cli("freeze", "poster-v1")
    git(repo.root, "add", "-A")
    git(repo.root, "commit", "-qm", "base")
    repo.cli("verify", "MTOW", "--note", "brief 2.1")
    md = repo.root / "r.md"
    p = repo.cli("check", "--no-lint", "--since", "HEAD", "--md", str(md), check=False)
    assert p.returncode == 0                               # not a frozen-value change
    text = md.read_text()
    assert "Verification changes" in text and "`MTOW`: verified by T: brief 2.1" in text
    assert "1/2 verified" in text
