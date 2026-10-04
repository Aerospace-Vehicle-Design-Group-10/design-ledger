function status = check(varargin)
%LEDGER.CHECK  Same as `ledger check` in a terminal.
%   ledger.check()
    [s, ~] = runCli(findRoot(''), [{'check'}, cellfun(@char, varargin, 'UniformOutput', false)], true);
    if nargout, status = s; end
end
