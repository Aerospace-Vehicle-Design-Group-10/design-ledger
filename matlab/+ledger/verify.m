function verify(names, opts)
%LEDGER.VERIFY  Record that you checked these values by hand.
%   ledger.verify("MTOW")
%   ledger.verify(["n_pax" "cargo_mass"], note="brief 2.1")
%
%   Same as `ledger verify` in a terminal. The verification is tied to the
%   current value: if the value changes later, it is cleared automatically.
    arguments
        names string
        opts.note (1,1) string = ""
    end
    args = [{'verify'}, cellstr(names)];
    if strlength(opts.note) > 0
        args = [args, {'--note', char(opts.note)}];
    end
    runCli(findRoot(''), args, true);
end
