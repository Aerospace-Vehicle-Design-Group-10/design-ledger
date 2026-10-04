function [stamp, recs] = loadRecords(root)
%LOADRECORDS  All parameters as a containers.Map name -> record struct.
%   Cached until a params/*.json file changes.
    cfg = jsondecode(fileread(fullfile(root, 'ledger.json')));
    pdir = 'params';
    if isfield(cfg, 'params_dir')
        pdir = cfg.params_dir;
    end
    files = dir(fullfile(root, pdir, '*.json'));
    stamp = strjoin(arrayfun(@(f) sprintf('%s:%.10f:%d', f.name, f.datenum, f.bytes), files, ...
        'UniformOutput', false), '|');
    S = stateStore();
    if isKey(S.cache, root)
        c = S.cache(root);
        if strcmp(c.stamp, stamp)
            recs = c.recs;
            return
        end
    end
    recs = containers.Map('KeyType', 'char', 'ValueType', 'any');
    for i = 1:numel(files)
        txt = fileread(fullfile(files(i).folder, files(i).name));
        if isempty(strtrim(txt))
            continue
        end
        try
            data = jsondecode(txt);
        catch err
            error('ledger:broken', 'params/%s is not valid JSON: %s', files(i).name, err.message);
        end
        names = fieldnames(data);
        for j = 1:numel(names)
            if ~isKey(recs, names{j})
                recs(names{j}) = data.(names{j});
            end
        end
    end
    S.cache(root) = struct('stamp', stamp, 'recs', recs);
end
