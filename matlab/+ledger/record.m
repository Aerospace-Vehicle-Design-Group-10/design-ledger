function rec = record(name)
%LEDGER.RECORD  Full record of a parameter (value, units, source, inputs...).
%   Not logged as a read.
    arguments
        name (1,1) string
    end
    [~, recs] = loadRecords(findRoot(callerFile()));
    if ~isKey(recs, char(name))
        error('ledger:missing', '''%s'' isn''t in the registry.', name);
    end
    rec = recs(char(name));
end
