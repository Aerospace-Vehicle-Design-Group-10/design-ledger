function override(varargin)
%LEDGER.OVERRIDE  What-if values for ledger.get. Nothing can be published while active.
%   ledger.override("wing_AR", 10, "wing_S", 125)   % set
%   ledger.override()                               % clear all
    S = stateStore();
    if nargin == 0
        remove(S.overrides, keys(S.overrides));
        fprintf('ledger: overrides cleared\n');
        return
    end
    if mod(nargin, 2) ~= 0
        error('ledger:override', 'Use name/value pairs: ledger.override("wing_AR", 10)');
    end
    for i = 1:2:nargin
        S.overrides(char(varargin{i})) = varargin{i+1};
    end
    fprintf('ledger: overriding %s (publishing is disabled until ledger.override())\n', ...
        strjoin(cellfun(@char, varargin(1:2:end), 'UniformOutput', false), ', '));
end
