"""Edge cases documented in the README's "Exact behaviour and edge cases" section."""
from conftest import Repo


def seed(repo: Repo):
    repo.set("MTOW", 712000, "N")
    repo.set("S", 120, "m^2")


def test_begin_inside_step_does_not_crash(repo):
    seed(repo)
    repo.script("weights/b.py", """
ledger.get("MTOW")
with ledger.step():
    ledger.get("S")
    ledger.begin()                      # forget everything read so far, at every level
    w = ledger.get("MTOW")
    ledger.publish("inner", w, units="N")
ledger.publish("outer", 1, units="-")
""")
    repo.run("weights/b.py")
    p = repo.params("weights")
    assert set(p["inner"]["inputs"]) == {"MTOW"}       # S was forgotten by begin()
    assert set(p["outer"]["inputs"]) == {"MTOW"}       # only the post-begin read came out


def test_step_does_not_see_reads_from_before_it(repo):
    """The documented under-report: re-get inside the block."""
    seed(repo)
    repo.script("weights/trap.py", """
W0 = ledger.get("MTOW")
with ledger.step():
    S = ledger.get("S")
    ledger.publish("WS", W0 / S, units="N/m^2")
""")
    repo.run("weights/trap.py")
    assert set(repo.params("weights")["WS"]["inputs"]) == {"S"}


def test_discipline_for_existing_name_must_match(repo):
    seed(repo)                                          # S lives in requirements
    repo.script("wing/collide.py", 'ledger.publish("S", 125, units="m^2", discipline="wing")\n')
    p = repo.run("wing/collide.py", check=False)
    assert p.returncode != 0 and "already lives in params/requirements.json" in p.stderr
    assert repo.params("requirements")["S"]["value"] == 120          # not overwritten


def test_discipline_matching_existing_file_is_fine(repo):
    seed(repo)
    repo.script("wing/ok.py", 'ledger.publish("S", 125, units="m^2", discipline="requirements")\n')
    repo.run("wing/ok.py")
    assert repo.params("requirements")["S"]["value"] == 125


def test_unknown_discipline_names_it(repo):
    seed(repo)
    repo.script("wing/bad.py", 'ledger.publish("new_thing", 1, units="-", discipline="wnig")\n')
    p = repo.run("wing/bad.py", check=False)
    assert "don't know this discipline: 'wnig'" in p.stderr


def test_republish_without_note_drops_it_and_lists_collapse(repo):
    seed(repo)
    repo.script("weights/n.py", """
ledger.publish("x", 1.0, units="-", note="first")
ledger.publish("x", 2.0, units="-")
ledger.publish("one", [5.0], units="-")
""")
    repo.run("weights/n.py")
    p = repo.params("weights")
    assert "note" not in p["x"] and p["x"]["value"] == 2
    assert p["one"]["value"] == 5


def test_empty_inputs_makes_it_assumed(repo):
    seed(repo)
    repo.script("weights/a.py", """
ledger.get("MTOW")
ledger.publish("z", 3, units="-", inputs=[])
""")
    repo.run("weights/a.py")
    assert repo.params("weights")["z"]["status"] == "assumed"
