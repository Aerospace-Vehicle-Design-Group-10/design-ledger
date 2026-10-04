function value = get(name)
%LEDGER.GET  Value of a shared design parameter.
%   W0 = ledger.get("MTOW");
%
%   The read is remembered, so whatever this script publishes next records
%   MTOW (and the value it had) as one of its inputs. Start each script with
%   ledger.begin() so reads from an earlier script don't count.
    arguments
        name (1,1) string
    end
    name = char(name);
    S = stateStore();
    if isKey(S.overrides, name)
        value = S.overrides(name);
        return
    end
    [~, recs] = loadRecords(findRoot(callerFile()));
    if ~isKey(recs, name)
        k = keys(recs);
        close = k(startsWith(lower(k), lower(name(1:min(3, end)))));
        hint = '';
        if ~isempty(close)
            hint = sprintf(' Similar: %s.', strjoin(close(1:min(5, end)), ', '));
        end
        error('ledger:missing', '''%s'' isn''t in the registry yet.%s', name, hint);
    end
    rec = recs(name);
    value = rec.value;
    S.reads(name) = value;
end
