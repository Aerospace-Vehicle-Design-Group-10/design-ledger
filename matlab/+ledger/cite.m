function cite(reference, names)
%LEDGER.CITE  Say where values came from, without changing them.
%   ledger.cite("AVD brief 2026-27, §2.1", ["n_pax" "cargo_mass"])
%
%   Same as `ledger cite` in a terminal. Works on frozen values too.
    arguments
        reference (1,1) string
        names string
    end
    runCli(findRoot(''), [{'cite', char(reference)}, cellstr(names)], true);
end
