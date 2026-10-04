function f = callerFile()
%CALLERFILE  The nearest user file (script or function) on the call stack:
%   the one that called ledger, which is where the computation lives.
    st = dbstack('-completenames');
    here = fileparts(fileparts(mfilename('fullpath')));   % .../+ledger
    mroot = matlabroot;
    f = '';
    for i = 1:numel(st)
        p = st(i).file;
        if isempty(p) || startsWith(p, here) || startsWith(p, mroot)
            continue
        end
        f = p;
        return
    end
end
