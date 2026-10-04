function status = sync(varargin)
%LEDGER.SYNC  Same as `ledger sync` in a terminal.
%   ledger.sync()
    [s, ~] = runCli(findRoot(''), [{'sync'}, cellfun(@char, varargin, 'UniformOutput', false)], true);
    if nargout, status = s; end
end
