function show(name)
%LEDGER.SHOW  One parameter: value, where it came from, whether it's stale, who uses it.
%   ledger.show("CG_x")
    arguments
        name (1,1) string
    end
    runCli(findRoot(''), {'show', char(name)}, true);
end
