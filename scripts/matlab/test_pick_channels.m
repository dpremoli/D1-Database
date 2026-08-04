function test_pick_channels(varargin)
%TEST_PICK_CHANNELS  Compare the old version-inference channel selection against
%the new VariableNames-driven selection in process_force.m.
%
%   Confirms that the fix changes ONLY the files it is meant to change:
%     * v0.5 (no VariableNames) and v0.1 / v1.0 -> identical output (regression)
%     * v0.9 truncated + "declares v1.0, wrong columns" -> corrected
%
%   test_pick_channels()            % run the built-in file set
%   test_pick_channels(path, ...)   % run on specific files

ROOT = 'Z:\star_group1\Shared\Machining\FRM';
if isempty(varargin)
    files = {
      fullfile(ROOT, '10. FRF Matrix + Extra\3. Data\Jozef WAM\114-AG-ME-2024-12-4-F3-30MPM_0.1feed_0.1DoC.mat'), 'X: declares v1.0, v0.9 columns'
      fullfile(ROOT, '9. Ti-17 + Pizza Trials (Dillon)\2. Data\Hammer-Y.mat'),                                    'V: truncated, no tacho'
      fullfile(ROOT, '10. FRF Matrix + Extra\3. Data\ITP Samples\98-AA-MF-2024-11-1\98-AA-MF-2024-11-1-R2-30MPM_0.15feed_0.3DoC.mat'), 'A: true v1.0'
      fullfile(ROOT, '8. Milling trials (Jozef)\1. Data\1. MAT\16-AA-MO-2017-6-18_Step4.mat'),                    'C: v0.5 (regression)'
      fullfile(ROOT, '2. Standard Ti-64 Billet (Emily)\2. Force Data\C1_Dia204-50MPM-04.mat'),                    'C: v0.1 13-col (regression)'
    };
else
    files = [varargin(:), repmat({''}, numel(varargin), 1)];
end

NR = 5000;   % rows compared -- enough to prove channel identity, cheap to read
fprintf('\n%-34s %-26s %-26s %s\n', 'file', 'OLD (version inference)', 'NEW (VariableNames)', 'verdict');
fprintf('%s\n', repmat('-', 1, 130));

nchanged = 0; nsame = 0; nfail = 0;
for k = 1:size(files, 1)
    p = files{k,1};
    [~, nm] = fileparts(p);
    try
        oErr = '';
        try
            [oF, oT, oLab] = old_pick(p, NR);
        catch OME
            oErr = OME.message; oLab = 'CRASHES';
        end
        [nF, nT, nLab] = new_pick(p, NR);

        if ~isempty(oErr)
            nchanged = nchanged + 1;
            fprintf('%-34s %-26s %-26s %s  [%s]\n', trunc(nm,33), oLab, nLab, ...
                'FIXED (old errored)', files{k,2});
            continue;
        end

        sameF = isequal(size(oF), size(nF)) && max(abs(oF(:) - nF(:))) < 1e-9;
        sameT = (isempty(oT) && isempty(nT)) || ...
                (~isempty(oT) && ~isempty(nT) && numel(oT) == numel(nT) && max(abs(oT(:) - nT(:))) < 1e-9);
        if sameF && sameT
            verdict = 'UNCHANGED'; nsame = nsame + 1;
        else
            verdict = 'CHANGED'; nchanged = nchanged + 1;
        end
        fprintf('%-34s %-26s %-26s %s  [%s]\n', trunc(nm,33), oLab, nLab, verdict, files{k,2});
    catch ME
        nfail = nfail + 1;
        fprintf('%-34s %-26s %-26s ERROR: %s\n', trunc(nm,33), '-', '-', ME.message);
    end
end
fprintf('%s\n', repmat('-', 1, 130));
fprintf('unchanged=%d  changed=%d  errors=%d\n\n', nsame, nchanged, nfail);
end

% --------------------------------------------------------------------
function [forces, tacho, lab] = old_pick(p, NR)
% The pre-fix logic, verbatim.
mf = matfile(p); vars = who(mf);
ts = [];
if ismember('data', vars);      nm = 'data'; ver = 0.5;
elseif ismember('DATA', vars);  nm = 'DATA'; ver = 0.1;
else; error('no data/DATA'); end
meta = struct();
if ismember('metadata', vars); meta = mf.metadata; end
if isfield(meta, 'fileVersion'); ver = double(meta.fileVersion); end

D = readrows(mf, nm, NR);
if ismember('timestamps', vars); ts = readrows(mf, 'timestamps', NR); end

if ver >= 1.0
    forces = sumdyno(D(:, 2:9)); tacho = D(:, 10);  lab = 'v1.0 -> cols 2:9';
elseif ver >= 0.5
    forces = sumdyno(D(:, 1:8)); tacho = D(:, 9);   lab = 'v0.5 -> cols 1:8';
else
    forces = D(:, 2:4);          tacho = D(:, 13);  lab = 'v0.1 -> cols 2:4';
end
end

% --------------------------------------------------------------------
function [forces, tacho, lab] = new_pick(p, NR)
% The post-fix logic: VariableNames wins when present.
mf = matfile(p); vars = who(mf);
if ismember('data', vars);      nm = 'data'; ver = 0.5;
elseif ismember('DATA', vars);  nm = 'DATA'; ver = 0.1;
else; error('no data/DATA'); end
meta = struct();
if ismember('metadata', vars); meta = mf.metadata; end
if isfield(meta, 'fileVersion'); ver = double(meta.fileVersion); end
vn = {};
if ismember('VariableNames', vars); vn = mf.VariableNames; end

D = readrows(mf, nm, NR);
ts = [];
if ismember('timestamps', vars); ts = readrows(mf, 'timestamps', NR); end

tacho = [];
if ~isempty(vn)
    names = strtrim(cellfun(@(x) char(string(x)), vn(:)', 'uni', 0));
    col = @(n) find(strcmpi(names, n), 1);
    ix = col('Fx'); iy = col('Fy'); iz = col('Fz');
    raw = cellfun(col, {'Fx1','Fx2','Fy1','Fy2','Fz1','Fz2','Fz3','Fz4'}, 'uni', 0);
    itac = find(strncmpi(names, 'Tacho', 5), 1);
    if ~isempty(itac); tacho = D(:, itac); end
    if ~isempty(ix) && ~isempty(iy) && ~isempty(iz)
        forces = D(:, [ix iy iz]);
        lab = sprintf('VN/summed (%d col)', numel(names)); return;
    elseif all(~cellfun(@isempty, raw))
        forces = sumdyno(D(:, cell2mat(raw)));
        lab = sprintf('VN/raw-sum (%d col)', numel(names)); return;
    end
end
if ver >= 1.0
    forces = sumdyno(D(:, 2:9)); tacho = D(:, 10);  lab = 'inferred v1.0';
elseif ver >= 0.5
    forces = sumdyno(D(:, 1:8)); tacho = D(:, 9);   lab = 'inferred v0.5';
else
    forces = D(:, 2:4);          tacho = D(:, 13);  lab = 'inferred v0.1';
end
end

% --------------------------------------------------------------------
function X = readrows(mf, nm, NR)
% Read at most NR rows. v7.3 slices; v6/v7 must load the variable whole.
try
    X = mf.(nm)(1:NR, :);
catch
    X = mf.(nm);
    if size(X,1) > NR; X = X(1:NR, :); end
end
X = double(X);
end

function F = sumdyno(d)
d = double(d);
F = [d(:,1)+d(:,2), d(:,3)+d(:,4), d(:,5)+d(:,6)+d(:,7)+d(:,8)];
end

function s = trunc(s, n)
if numel(s) > n; s = [s(1:n-1) '~']; end
end
