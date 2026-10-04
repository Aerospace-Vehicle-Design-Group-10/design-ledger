function publish(name, value, units, opts)
%LEDGER.PUBLISH  Write a value to your local copy of the registry.
%   ledger.publish("CG_x", x_cg, "m");
%   ledger.publish("CG_x", x_cg, "m", note="fuel at 50%");
%   ledger.publish("CG_x", x_cg, "m", inputs=["MTOW" "wing_x_LE"]);
%
%   Records everything this script read with ledger.get as the value's
%   inputs, plus a fingerprint of the script. It only changes your local
%   files; `ledger.push("message")` shares it.
%
%   Options:
%     note        free text shown in reviews
%     desc        what the parameter is (kept across updates)
%     inputs      use only these names as inputs instead of everything read
%     discipline  which params/<discipline>.json for a NEW parameter
%                 (normally taken from the script's folder)
    arguments
        name (1,1) string
        value
        units (1,1) string
        opts.note (1,1) string = ""
        opts.desc (1,1) string = ""
        opts.inputs string = "<auto>"
        opts.discipline (1,1) string = ""
    end
    S = stateStore();
    if S.overrides.Count > 0
        error('ledger:override', ['Can''t publish while ledger.override is active: ' ...
            'what-if values must not reach the registry. Clear it with ledger.override().']);
    end
    if isstring(value)
        value = char(value);
    end

    p = struct();
    p.name = char(name);
    p.value = value;
    p.units = char(units);
    p.note = char(opts.note);
    p.desc = char(opts.desc);
    p.discipline = char(opts.discipline);
    if ~(isscalar(opts.inputs) && opts.inputs == "<auto>")
        p.inputs = cellstr(opts.inputs);
    end
    p.script = callerFile();
    p.cwd = pwd;
    r = struct();
    k = keys(S.reads);
    for i = 1:numel(k)
        r.(k{i}) = S.reads(k{i});
    end
    p.reads = r;

    f = [tempname '.json'];
    cleanup = onCleanup(@() delete(f));
    fid = fopen(f, 'w', 'n', 'UTF-8');
    fwrite(fid, jsonencode(p), 'char');
    fclose(fid);

    root = findRoot(p.script);
    [status, out] = runCli(root, {'_publish', '--payload', f}, false);
    out = strtrim(out);
    if status ~= 0
        error('ledger:publish', '%s', out);
    end
    if ~isempty(out)
        disp(out);
    end
end
