function push(message, opts)
%LEDGER.PUSH  Save your work to GitHub and open a pull request.
%   ledger.push("updated CG estimate")
%   ledger.push("WIP drag build-up", draft=true)
    arguments
        message (1,1) string
        opts.draft (1,1) logical = false
    end
    root = findRoot('');
    runCli(root, {'push', char(message), '--dry-run'}, true);
    answer = input('Push these? [Y/n] ', 's');
    if ~(isempty(answer) || any(strcmpi(strtrim(answer), {'y', 'yes'})))
        disp('Cancelled. Nothing changed.');
        return
    end
    args = {'push', char(message), '--yes'};
    if opts.draft
        args{end+1} = '--draft';
    end
    runCli(root, args, true);
end
