import ledger

cargo_m = ledger.get("cargo_mass")
CG_x = cargo_m * 0.1
ledger.publish("CG_x", CG_x, "m", discipline="fuselage")
