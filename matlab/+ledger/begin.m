function begin(label)
%LEDGER.BEGIN  Forget everything read so far.
%   ledger.begin()          % at the top of every script that publishes
%   ledger.begin("cg")      % optional label, for readability only
%
%   MATLAB keeps state between scripts in one session, so without this the
%   reads of a script you ran earlier would count as inputs of this one.
    arguments
        label (1,1) string = ""  %#ok<INUSA>
    end
    S = stateStore();
    remove(S.reads, keys(S.reads));
end
