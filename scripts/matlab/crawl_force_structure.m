function T = crawl_force_structure(root, outcsv, varargin)
%CRAWL_FORCE_STRUCTURE  Inventory the structure of every force .mat under ROOT.
%
%   T = crawl_force_structure(ROOT, OUTCSV)
%   T = crawl_force_structure(ROOT, OUTCSV, 'Workers', 8, 'Reference', REFPATH)
%
%   Reads only file HEADERS and the small `metadata` / `VariableNames` variables.
%   The force matrix (DATA/data), `timestamps` and `AmpSettings` are NEVER loaded --
%   an 11 GB capture is inspected in milliseconds.
%
%   Each file is classified against the current v1.0 standard documented in
%   docs/force-file-standards.md (conformance levels A/B/C/D/X).
%
%   Options
%     'Workers'    number of parallel workers (default: min(8, numcores)); 0 = serial
%     'Reference'  path to the canonical v1.0 file. Its metadata field list is used
%                  as the target schema instead of the hard-coded one below.
%     'Exclude'    cell array of path substrings to skip (default {'_dedup_removed'})
%
%   Example
%     crawl_force_structure('Z:\star_group1\Shared\Machining\FRM', 'force_inventory.csv')

p = inputParser;
p.addParameter('Workers',  min(8, feature('numcores')), @isnumeric);
p.addParameter('Reference', '', @(x) ischar(x) || isstring(x));
p.addParameter('Exclude',  {'_dedup_removed'}, @iscell);
p.parse(varargin{:});
opt = p.Results;

% ---- canonical v1.0 metadata schema (see docs/force-file-standards.md §3.2) ----
CANON = {'SampleName','OpType','Operation','OperationType','TriggerTime','Rate', ...
         'CutDiameter','SurfaceSpeed','MaxRPM','Notes','Feed','DepthOfCut', ...
         'Insert','EdgeID','Machine','Tool','New_Edge','Swarf','SwarfID', ...
         'Coolant','fileVersion','Dyno','Stream1'};
V10_ONLY = {'Operation','OperationType','EdgeID','SwarfID'};   % added in v1.0

if ~isempty(opt.Reference)
    fprintf('Deriving target schema from reference:\n  %s\n', opt.Reference);
    try
        r = load(char(opt.Reference), 'metadata');
        CANON = fieldnames(r.metadata)';
        fprintf('  -> %d metadata fields: %s\n\n', numel(CANON), strjoin(CANON, ', '));
    catch ME
        warning('reference read failed (%s); using built-in schema', ME.message);
    end
end

% ---- enumerate ----
fprintf('Scanning %s ...\n', root);
d = dir(fullfile(root, '**', '*.mat'));
d = d(~[d.isdir]);
paths = fullfile({d.folder}, {d.name});
keep = true(1, numel(paths));
for k = 1:numel(opt.Exclude)
    keep = keep & ~contains(paths, opt.Exclude{k}, 'IgnoreCase', true);
end
paths = paths(keep);
n = numel(paths);
fprintf('Found %d .mat files (after exclusions).\n', n);
if n == 0; T = table(); return; end

% ---- parallel pool ----
if opt.Workers > 1
    pool = gcp('nocreate');
    if isempty(pool) || pool.NumWorkers ~= opt.Workers
        if ~isempty(pool); delete(pool); end
        parpool('Processes', opt.Workers);
    end
    fprintf('Crawling with %d workers...\n', opt.Workers);
else
    fprintf('Crawling serially...\n');
end

recs = cell(n, 1);
t0 = tic;
fprintf('%5s %6s  %-13s %-19s %7s  %s\n', 'done', 'pct', 'format', 'grade', 'secs', 'file');
tick(0, n);                       % reset the progress counter
if opt.Workers > 1
    % parfor bodies cannot print in order, so workers post each finished record
    % back to the client through a DataQueue and the client prints it live.
    q = parallel.pool.DataQueue;
    afterEach(q, @(d) tick(d, n));
    parfor i = 1:n
        r = inspect(paths{i}, root, CANON, V10_ONLY);
        send(q, r);
        recs{i} = r;
    end
else
    for i = 1:n
        recs{i} = inspect(paths{i}, root, CANON, V10_ONLY);
        tick(recs{i}, n);
    end
end
fprintf('Done in %.1f s (%.2f s/file).\n', toc(t0), toc(t0)/n);

T = struct2table([recs{:}]);
T = sortrows(T, {'conformance', 'rel_path'});

if nargin >= 2 && ~isempty(outcsv)
    writetable(T, outcsv);
    fprintf('Wrote %s (%d rows x %d cols)\n', outcsv, height(T), width(T));
end

summarise(T);
end

% =====================================================================
function r = inspect(pth, root, CANON, V10_ONLY)
% Header-only inspection of one .mat.

r = blank(CANON);
r.rel_path = str(erase(pth, [root filesep]));
[fld, nm, ext] = fileparts(pth);
r.folder   = str(erase(fld, [root filesep]));
r.filename = str([nm ext]);

info = dir(pth);
if ~isempty(info); r.size_mb = info.bytes / 1e6; r.modified = str(datestr(info.datenum, 'yyyy-mm-dd HH:MM:SS')); end

tf = tic;
try
    fmt = matformat(pth);
    r.mat_format = str(fmt);
    isV73 = strcmp(fmt, 'v7.3 (HDF5)');

    % --- variable inventory ---
    % v7.3 is HDF5, so matfile() gives genuine partial access -- individual
    % variables are read without touching the rest of the file.
    % v6/v7 is a flat compressed stream: matfile() would inflate the WHOLE file
    % on first access, so use the header-only whos('-file') there instead.
    if isV73
        mf = matfile(pth);
        w  = whos(mf);
        r.read_method = str('matfile (partial)');
    else
        mf = [];
        w  = whos('-file', pth);
        r.read_method = str('whos -file');
    end
    names = {w.name};
    r.vars    = str(strjoin(names, '|'));
    r.n_vars  = numel(names);

    % --- locate the force matrix ---
    if ismember('data', names)
        idx = find(strcmp(names, 'data'), 1); r.data_var = str('data'); r.inferred_version = 0.5;
    elseif ismember('DATA', names)
        idx = find(strcmp(names, 'DATA'), 1); r.data_var = str('DATA'); r.inferred_version = 0.1;
    else
        idx = []; r.data_var = str(''); r.inferred_version = NaN;
    end
    if ~isempty(idx)
        sz = w(idx).size;
        r.n_rows        = sz(1);
        r.n_cols        = sz(end);
        r.matrix_class  = str(w(idx).class);
        r.matrix_mb     = w(idx).bytes / 1e6;
    end

    r.has_timestamps    = ismember('timestamps', names);
    r.has_variablenames = ismember('VariableNames', names);
    r.has_ampsettings   = ismember('AmpSettings', names);
    r.has_metadata      = ismember('metadata', names);
    if r.has_ampsettings
        r.ampsettings_kb = w(strcmp(names, 'AmpSettings')).bytes / 1e3;
    end
    if r.has_timestamps
        tsz = w(strcmp(names, 'timestamps')).size; r.ts_len = tsz(1);
    end

    % --- VariableNames (tiny cell) ---
    if r.has_variablenames
        vn = getvar(mf, pth, 'VariableNames');
        r.variable_names = str(strjoin(cellfun(@(x) char(string(x)), vn(:)', 'uni', 0), '|'));
    end

    % --- metadata (small struct; never touches the matrix) ---
    if r.has_metadata
        m = getvar(mf, pth, 'metadata');
        if isstruct(m) && ~isempty(m)
            m = m(1);
            have = fieldnames(m)';
            r.n_meta_fields = numel(have);
            r.missing_fields = str(strjoin(setdiff(CANON, have, 'stable'), '|'));
            r.extra_fields   = str(strjoin(setdiff(have, CANON, 'stable'), '|'));
            r.has_machinename = ismember('MachineName', have);

            for k = 1:numel(CANON)
                f = CANON{k};
                if isfield(m, f); r.(['m_' f]) = str(brief(m.(f))); end
            end
            if isfield(m, 'fileVersion')
                v = m.fileVersion;
                if isnumeric(v) && ~isempty(v); r.file_version = double(v(1)); end
            end
            if isfield(m, 'Dyno') && isstruct(m.Dyno) && isfield(m.Dyno, 'Gain')
                g = m.Dyno.Gain; if isnumeric(g) && ~isempty(g); r.dyno_gain = double(g(1)); end
            end
            if isfield(m, 'Rate')
                q = m.Rate; if isnumeric(q) && ~isempty(q); r.rate_hz = double(q(1)); end
            end
        end
    end

    % --- effective version + layout agreement ---
    ver = r.inferred_version;
    if ~isnan(r.file_version); ver = r.file_version; end
    r.effective_version = ver;

    if     ver >= 1.0; r.expected_cols = 10;
    elseif ver >= 0.5; r.expected_cols = 9;
    elseif ~isnan(ver); r.expected_cols = 13;
    end
    if ~isnan(r.expected_cols) && ~isnan(r.n_cols)
        r.cols_ok = (r.n_cols >= r.expected_cols);
        % declared version contradicts the layout that would have been inferred
        r.version_conflict = ~r.cols_ok || ...
            (~isnan(r.file_version) && r.file_version >= 1.0 && strcmp(char(r.data_var), 'data'));
    end

    r.conformance = str(grade(r, V10_ONLY));
    r.status = str('ok');
catch ME
    r.status = str('ERROR');
    r.error  = str(ME.message);
    r.conformance = str('E - unreadable');
end
r.read_secs = toc(tf);
end

% =====================================================================
function g = grade(r, V10_ONLY)
% Conformance level per docs/force-file-standards.md §5.
%
% Grading keys off the LAYOUT SIGNATURE (VariableNames), not the column count:
% the v1.0 and v0.9-truncated layouts both have 10 columns and an uppercase DATA,
% so a count-based check silently passes files whose channels are wrong.
V10 = 'Time|Fx1|Fx2|Fy1|Fy2|Fz1|Fz2|Fz3|Fz4|Tacho (ai0)';
V01 = 'Time|Fx|Fy|Fz|Fx1|Fx2|Fy1|Fy2|Fz1|Fz2|Fz3|Fz4|Tacho (ai0)';
V09 = 'Time|Fx|Fy|Fz|Fx1|Fx2|Fy1|Fy2|Fz1|Fz2';           % truncated: no Fz3/Fz4/Tacho
sig = char(r.variable_names);

% no recognisable force layout at all
if ~r.has_variablenames && (isnan(r.n_cols) || r.n_cols < 9)
    g = 'N - not a force capture'; return;
end

% a declared version that contradicts the actual signature is the worst case:
% the file parses without error but every channel is wrong.
if ~isnan(r.file_version) && r.file_version >= 1.0 && ~isempty(sig) && ~strcmp(sig, V10)
    g = 'X - inconsistent'; return;
end
if strcmp(sig, V09)
    g = 'V - truncated (no tacho)'; return;
end
if r.version_conflict && ~strcmp(sig, V01)
    g = 'X - inconsistent'; return;
end
if ~r.has_metadata
    g = 'D - legacy, no metadata'; return;
end
if r.effective_version >= 1.0
    missing = string(r.missing_fields);
    lacksV10 = any(cellfun(@(f) contains(missing, f), V10_ONLY));
    if r.has_ampsettings && r.has_variablenames && strlength(missing) == 0
        g = 'A - current';
    elseif lacksV10 || ~r.has_ampsettings || ~r.has_variablenames || strlength(missing) > 0
        g = 'B - current layout, thin metadata';
    else
        g = 'A - current';
    end
    return;
end
g = 'C - legacy layout, has metadata';
end

% =====================================================================
function tick(d, n)
% Live progress line, one per completed file. Call tick(0, n) to reset.
% Counts on the client, so it is correct under parfor even though the files
% themselves complete out of order.
persistent c t0
if isnumeric(d) && isscalar(d) && d == 0
    c = 0; t0 = tic; return;
end
c = c + 1;
el  = toc(t0);
eta = el / max(c, 1) * (n - c);
g = char(d.conformance);
if numel(g) > 19; g = g(1:19); end
fprintf('%3d/%3d %5.1f%%  %-13s %-19s %6.1fs  %s   [elapsed %4.0fs eta %4.0fs]\n', ...
    c, n, 100*c/n, char(d.mat_format), g, d.read_secs, char(d.filename), el, eta);
end

% =====================================================================
function v = getvar(mf, pth, name)
% Read one small variable. MF is a matfile handle for v7.3 files (partial read,
% never touches the force matrix) or [] for v6/v7, where a named load is the
% cheapest option available -- matfile() on those inflates the entire file.
if ~isempty(mf)
    v = mf.(name);
else
    s = load(pth, name);
    v = s.(name);
end
end

% =====================================================================
function f = matformat(pth)
% v7.3 files are HDF5 behind a 128-byte text header; v6/v7 are "MATLAB 5.0".
f = 'unknown';
fid = fopen(pth, 'r');
if fid < 0; return; end
c = onCleanup(@() fclose(fid));
hdr = fread(fid, 128, '*char')';
if     contains(hdr, 'MATLAB 7.3'); f = 'v7.3 (HDF5)';
elseif contains(hdr, 'MATLAB 5.0'); f = 'v6/v7';
elseif isempty(hdr);                f = 'empty';
end
end

% =====================================================================
function s = brief(v)
% One-line printable form of a metadata value. Structs/cells are summarised,
% never expanded -- keeps the CSV a spreadsheet, not a dump.
try
    if ischar(v);        s = v;
    elseif isstring(v);  s = char(strjoin(v(:)', ' '));
    elseif islogical(v); s = mat2str(v);
    elseif isnumeric(v)
        if isempty(v);        s = '';
        elseif numel(v) <= 6; s = mat2str(v);
        else;                 s = sprintf('<%s>', mat2str(size(v)));
        end
    elseif isdatetime(v); s = char(string(v, 'yyyy-MM-dd HH:mm:ss'));
    elseif iscell(v)
        parts = cellfun(@(x) string(brief(x)), v(:)', 'uni', 1);
        s = char(strjoin(parts, ';'));
    elseif isstruct(v);  s = sprintf('struct{%s}', strjoin(fieldnames(v(1))', ','));
    else;                s = sprintf('<%s>', class(v));
    end
catch
    s = sprintf('<%s>', class(v));
end
s = strtrim(regexprep(s, '\s+', ' '));
if numel(s) > 200; s = [s(1:200) '...']; end
end

% =====================================================================
function r = blank(CANON)
r = struct( ...
    'rel_path', str(''), 'folder', str(''), 'filename', str(''), ...
    'conformance', str(''), 'status', str(''), 'error', str(''), ...
    'size_mb', NaN, 'modified', str(''), 'mat_format', str(''), ...
    'read_method', str(''), ...
    'n_vars', NaN, 'vars', str(''), ...
    'data_var', str(''), 'n_rows', NaN, 'n_cols', NaN, ...
    'matrix_class', str(''), 'matrix_mb', NaN, ...
    'inferred_version', NaN, 'file_version', NaN, 'effective_version', NaN, ...
    'expected_cols', NaN, 'cols_ok', false, 'version_conflict', false, ...
    'has_timestamps', false, 'ts_len', NaN, ...
    'has_variablenames', false, 'variable_names', str(''), ...
    'has_ampsettings', false, 'ampsettings_kb', NaN, ...
    'has_metadata', false, 'has_machinename', false, ...
    'n_meta_fields', NaN, 'missing_fields', str(''), 'extra_fields', str(''), ...
    'rate_hz', NaN, 'dyno_gain', NaN, 'read_secs', NaN);
for k = 1:numel(CANON)
    r.(['m_' CANON{k}]) = str('');
end
end

function s = str(x)
s = string(x);
end

% =====================================================================
function summarise(T)
fprintf('\n================ SUMMARY ================\n');
[g, names] = findgroups(T.conformance);
cnt = splitapply(@numel, T.rel_path, g);
for i = 1:numel(names)
    fprintf('  %-38s %4d  (%.0f%%)\n', names(i), cnt(i), 100*cnt(i)/height(T));
end
fprintf('  %-38s %4d\n', 'TOTAL', height(T));

fprintf('\n-- effective version --\n');
v = T.effective_version; uv = unique(v(~isnan(v)));
for i = 1:numel(uv); fprintf('  v%-37.2f %4d\n', uv(i), sum(v == uv(i))); end
if any(isnan(v)); fprintf('  %-38s %4d\n', '(undetermined)', sum(isnan(v))); end

fprintf('\n-- mat format --\n');
[g2, n2] = findgroups(T.mat_format);
c2 = splitapply(@numel, T.rel_path, g2);
for i = 1:numel(n2); fprintf('  %-38s %4d\n', n2(i), c2(i)); end

fprintf('\n-- read method (mean secs/file) --\n');
[g3, n3] = findgroups(T.read_method);
c3 = splitapply(@numel, T.rel_path, g3);
s3 = splitapply(@(x) mean(x, 'omitnan'), T.read_secs, g3);
for i = 1:numel(n3); fprintf('  %-38s %4d  %6.2f s\n', n3(i), c3(i), s3(i)); end

fprintf('\n-- flags --\n');
fprintf('  %-38s %4d\n', 'has AmpSettings',        sum(T.has_ampsettings));
fprintf('  %-38s %4d\n', 'has VariableNames',      sum(T.has_variablenames));
fprintf('  %-38s %4d\n', 'no metadata struct',     sum(~T.has_metadata));
fprintf('  %-38s %4d\n', 'legacy MachineName',     sum(T.has_machinename));
fprintf('  %-38s %4d\n', 'VERSION/LAYOUT CONFLICT', sum(T.version_conflict));
fprintf('  %-38s %4.1f\n', 'total size (GB)',      sum(T.size_mb, 'omitnan')/1000);
fprintf('=========================================\n');
end
