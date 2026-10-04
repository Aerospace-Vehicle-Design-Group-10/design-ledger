import json

from conftest import Repo


def test_csv_export(repo: Repo):
    (repo.root / "export").mkdir()
    (repo.root / "export/designparams_template.csv").write_text(
        "Property,Value,Comments\n"
        "Maximum Takeoff Weight [N],1,\n"
        "Wing front spar position [% chord],2,\n"
        "Engine cruise sfc [lbs/hr/lbf],3,\n"
        "Outermost Engine spanwise position [m],4,as above. If twin engine aircraft enter NaN\n"
        "Reverse thrust used?,5,\"[0 = no, 1 = yes]\"\n"
        "Wing airfoil section,6,\n"
        "Wing Ref Area [m^2],7,\n"
    )
    (repo.root / "export/designparams_map.json").write_text(json.dumps({
        "Maximum Takeoff Weight [N]": {"param": "MTOW"},
        "Wing front spar position [% chord]": {"param": "wing_front_spar", "scale": 100},
        "Engine cruise sfc [lbs/hr/lbf]": {"param": "sfc", "scale": 3600},
        "Outermost Engine spanwise position [m]": {"param": "engine_y_outer", "missing": "NaN"},
        "Reverse thrust used?": {"param": "reverse_thrust"},
        "Wing airfoil section": {"param": "wing_airfoil"},
        "Wing Ref Area [m^2]": {"param": "wing_S"},
    }))
    repo.set("MTOW", 712000, "N")
    repo.set("wing_front_spar", 0.15, "-", "wing")
    repo.set("sfc", 1.5e-4, "1/s", "wing")
    repo.set("reverse_thrust", True, "-", "wing")
    repo.cli("set", "wing_airfoil", "NACA 23015", "--units", "-", "--discipline", "wing")
    out = repo.cli("export", "csv").stdout
    assert "1 rows have no value yet" in out and "wing_S" in out
    lines = (repo.root / "export/designparams.csv").read_text().splitlines()
    assert lines[1] == "Maximum Takeoff Weight [N],712000,"
    assert lines[2] == "Wing front spar position [% chord],15,"
    assert lines[3] == "Engine cruise sfc [lbs/hr/lbf],0.54,"
    assert lines[4].startswith("Outermost Engine spanwise position [m],NaN,")
    assert lines[5] == 'Reverse thrust used?,1,"[0 = no, 1 = yes]"'
    assert lines[6] == "Wing airfoil section,NACA 23015,"
    assert lines[7] == "Wing Ref Area [m^2],,"


def test_tex_export(repo: Repo):
    repo.set("MTOW", 712000, "N")
    repo.set("wing_S", 122.4, "m^2", "wing")
    repo.cli("export", "tex", "--out", str(repo.root / "p.tex"))
    tex = (repo.root / "p.tex").read_text()
    assert r"\csname ledger@v@MTOW\endcsname{712000}" in tex
    assert r"\csname ledger@u@wing_S\endcsname{m^2}" not in tex      # ^ is escaped
    assert r"\csname ledger@u@wing_S\endcsname{m\^{}2}" in tex
