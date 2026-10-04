function S = stateStore()
%STATESTORE  Session state shared by the ledger functions (maps are handles).
    persistent st
    if isempty(st)
        st = struct( ...
            'reads',     containers.Map('KeyType', 'char', 'ValueType', 'any'), ...
            'overrides', containers.Map('KeyType', 'char', 'ValueType', 'any'), ...
            'cache',     containers.Map('KeyType', 'char', 'ValueType', 'any'));
    end
    S = st;
end
