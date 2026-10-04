function [status, out] = runCli(root, args, echo)
%RUNCLI  Run `python -m ledger <args>` from the design repo.
%   Uses the Python recorded by `ledger setup` (.ledger/local.json), and the
%   PATH it saw, so git/gh are found even when MATLAB was opened from the Dock.
    py = '';
    pathEnv = '';
    lp = fullfile(root, '.ledger', 'local.json');
    if isfile(lp)
        s = jsondecode(fileread(lp));
        if isfield(s, 'python'), py = s.python; end
        if isfield(s, 'path'), pathEnv = s.path; end
    end
    if isempty(py)
        error('ledger:setup', 'Run setup.m in the design repo first (it installs the ledger tools).');
    end
    q = @(s) ['"' strrep(char(s), '"', '\"') '"'];
    cmd = [q(py) ' -m ledger'];
    for i = 1:numel(args)
        cmd = [cmd ' ' q(args{i})]; %#ok<AGROW>
    end

    if ispc
        cmd = ['"' cmd '"'];   % cmd.exe strips the outer pair of quotes
    end

    oldRoot = getenv('LEDGER_ROOT');
    oldPath = getenv('PATH');
    oldIO = getenv('PYTHONIOENCODING');
    restore = onCleanup(@() cellfun(@setenv, {'LEDGER_ROOT', 'PATH', 'PYTHONIOENCODING'}, ...
        {oldRoot, oldPath, oldIO}));
    setenv('LEDGER_ROOT', root);
    setenv('PYTHONIOENCODING', 'utf-8');
    if ~isempty(pathEnv)
        setenv('PATH', pathEnv);
    end
    if echo
        [status, out] = system(cmd, '-echo');
    else
        [status, out] = system(cmd);
    end
end
