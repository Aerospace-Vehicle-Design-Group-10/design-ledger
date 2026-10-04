function r = reads()
%LEDGER.READS  What this script has read so far (the inputs a publish would record).
    S = stateStore();
    r = struct();
    k = keys(S.reads);
    for i = 1:numel(k)
        r.(k{i}) = S.reads(k{i});
    end
    if nargout == 0
        disp(r);
        clear r
    end
end
