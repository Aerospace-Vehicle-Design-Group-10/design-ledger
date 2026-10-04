function root = findRoot(startFile)
%FINDROOT  Walk up from startFile (or pwd) to the folder holding ledger.json.
    starts = {};
    env = getenv('LEDGER_ROOT');
    if ~isempty(env)
        starts{end+1} = env;
    end
    if ~isempty(startFile)
        starts{end+1} = fileparts(char(startFile));
    end
    starts{end+1} = pwd;
    for i = 1:numel(starts)
        d = starts{i};
        while true
            if isfile(fullfile(d, 'ledger.json'))
                root = d;
                return
            end
            parent = fileparts(d);
            if isempty(parent) || strcmp(parent, d)
                break
            end
            d = parent;
        end
    end
    error('ledger:root', ['Can''t find ledger.json. cd into the design repo ' ...
        '(or a folder inside it) and run setup.m once.']);
end
