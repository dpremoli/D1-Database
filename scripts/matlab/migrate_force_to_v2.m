function rep = migrate_force_to_v2(src, dst, varargin)
%MIGRATE_FORCE_TO_V2  Convert a legacy force capture (v0.1/v0.5/v0.9/v1.0) to the
%self-describing v2.0 multi-stream schema.
%
%   rep = migrate_force_to_v2(SRC, DST)
%   rep = migrate_force_to_v2(SRC, DST, 'ChunkRows', 5e6, 'DryRun', false)
%
% See docs/superpowers/specs/2026-07-27-force-capture-v2-schema-design.md.
%
% The conversion is a pure column remap into named streams -- no resampling, no
% arithmetic, nothing discarded. The source is opened read-only and never
% modified; output is a new v7.3 file. Force channels are stored RAW (the summed
% Fx/Fy/Fz are reconstructed on read, so they are not written here).
%
% Output variables (see spec "File layout"):
%   formatVersion         2.0
%   capture               struct  (legacy metadata + schema/provenance/completeness)
%   streams               struct  (per-stream + per-channel descriptors, pointers)
%   AmpSettings           struct  (verbatim, when the source had it)
%   stream__force__data   [N x C] raw force channels
%   stream__force__time   [N x 1]
%   stream__tacho__data   [N x 1] (omitted when the source has no tacho)
%   stream__tacho__time   [N x 1]

p = inputParser;
p.addParameter('ChunkRows', 5e6, @isnumeric);
p.addParameter('DryRun', false, @islogical);
p.addParameter('Verify', true, @islogical);
p.parse(varargin{:});
opt = p.Results;

rep = struct('src', string(src), 'dst', string(dst), 'from_layout', "", ...
             'status', "", 'note', "", 'rows', NaN, 'force_cols', NaN, ...
             'has_tacho', false, 'secs', NaN);
t0 = tic;

% ---- resolve source layout (VariableNames first, then inference) -----------
mi   = matfile(src);
vars = who(mi);
if ismember('data', vars);      dvar = 'data'; ver = 0.5;
elseif ismember('DATA', vars);  dvar = 'DATA'; ver = 0.1;
else; rep.status = "SKIP"; rep.note = "no data/DATA variable"; return; end

meta = struct();
if ismember('metadata', vars); meta = mi.metadata; meta = meta(1); end
if isfield(meta, 'fileVersion'); ver = double(meta.fileVersion(1)); end

vn = {};
if ismember('VariableNames', vars); vn = mi.VariableNames; end
if ismember('AmpSettings', vars); amp = mi.AmpSettings; else; amp = []; end

w = whos(mi);
sz = w(strcmp({w.name}, dvar)).size;
N = sz(1); ncol = sz(end);
rep.rows = N;

% column roles from VariableNames when present, else from the version layout
[fcols, tcol, timecol, layout] = resolve_columns(vn, ver, dvar, ncol, vars);
rep.from_layout = string(layout);
rep.force_cols  = numel(fcols);
rep.has_tacho   = ~isempty(tcol);

if opt.DryRun
    rep.status = "DRYRUN";
    rep.note = sprintf('%s: force cols [%s], tacho %s, N=%d', layout, ...
        num2str(fcols), mat2str(~isempty(tcol)), N);
    rep.secs = toc(t0); return;
end

% ---- prepare output --------------------------------------------------------
if exist(dst, 'file'); delete(dst); end
d = fileparts(dst); if ~isempty(d) && ~isfolder(d); mkdir(d); end
formatVersion = 2.0;                          % bootstrap the file with a real variable
save(dst, 'formatVersion', '-v7.3');
mo = matfile(dst, 'Writable', true);

isV73src = is_v73(src);
step = max(1, floor(opt.ChunkRows));
if ~isV73src
    % v6/v7 has no partial read; pull the big variables into memory once.
    Dfull = double(mi.(dvar));
    if strcmp(dvar, 'data') && ismember('timestamps', vars)
        Tfull = double(mi.timestamps);
    else
        Tfull = [];
    end
end

for i = 1:step:N
    j = min(i + step - 1, N);
    if isV73src
        blk = double(mi.(dvar)(i:j, :));
        if isempty(timecol) && strcmp(dvar, 'data') && ismember('timestamps', vars)
            tb = double(mi.timestamps(i:j, 1));
        else
            tb = [];
        end
    else
        blk = Dfull(i:j, :);
        if ~isempty(Tfull); tb = Tfull(i:j, 1); else; tb = []; end
    end

    % time vector for this chunk
    if ~isempty(timecol)
        tt = blk(:, timecol);
    elseif ~isempty(tb)
        tt = tb;
    else
        tt = ((i-1):(j-1))';                  % last-resort synthetic index
    end

    mo.stream__force__data(i:j, 1:numel(fcols)) = blk(:, fcols);
    mo.stream__force__time(i:j, 1)              = tt;
    if ~isempty(tcol)
        mo.stream__tacho__data(i:j, 1) = blk(:, tcol);
        mo.stream__tacho__time(i:j, 1) = tt;
    end
end

% ---- descriptors -----------------------------------------------------------
Fs = getnum(meta, 'Rate', NaN);

fchan = force_channels(vn, fcols);
force = stream_struct('Dyno', getdev(meta, 'Dyno'), Fs, N, ...
    'stream__force__data', 'stream__force__time', fchan);
force.gain = getnested(meta, {'Dyno','Gain'}, 1);
if ~isempty(amp); force.amp_settings_var = 'AmpSettings'; else; force.amp_settings_var = ''; end

streams = struct('force', force);
if ~isempty(tcol)
    tchan = struct('name','Tacho','role','tacho','axis','','unit','V', ...
        'bits',NaN,'device',getdev(meta,'Stream1'),'sensitivity',NaN, ...
        'physical_range',NaN,'derived',false);
    streams.tacho = stream_struct('Stream1', getdev(meta,'Stream1'), Fs, N, ...
        'stream__tacho__data', 'stream__tacho__time', tchan);
end

% ---- capture block ---------------------------------------------------------
capture = meta;
capture.schemaVersion  = 2;
capture.time_sync_model = 'shared_origin';
capture.completeness   = completeness(vn, fcols, ~isempty(tcol));
capture.provenance     = struct('from_layout', layout, 'source_file', string(src), ...
    'tool', 'migrate_force_to_v2', ...
    'when', string(datetime('now','Format','yyyy-MM-dd HH:mm:ss')));

% ---- write the small descriptor variables ----------------------------------
mo.capture = capture;
mo.streams = streams;
if ~isempty(amp); mo.AmpSettings = amp; end
clear mo

% ---- verify ----------------------------------------------------------------
if opt.Verify
    mv = matfile(dst);
    stride = max(1, floor(N / 2000));         % MatFile ranges must be equally spaced
    probe  = 1:stride:N;
    A = double(mv.stream__force__data(probe, :));
    if isV73src
        B = double(mi.(dvar)(probe, :)); B = B(:, fcols);
    else
        B = Dfull(probe, fcols);
    end
    dF = max(abs(A(:) - B(:)));
    if ~(dF == 0)
        rep.status = "FAIL"; rep.note = sprintf('force mismatch max|diff|=%g', dF);
        rep.secs = toc(t0); return;
    end
    rep.note = sprintf('%s -> v2.0: force[%dx%d]%s, verified %d probe rows exact', ...
        layout, N, numel(fcols), ternary(~isempty(tcol),' +tacho',''), numel(probe));
end

rep.status = "OK";
rep.secs   = toc(t0);
end

% ===================================================================== helpers
function [fcols, tcol, timecol, layout] = resolve_columns(vn, ver, dvar, ncol, vars)
% Returns force-channel column indices, tacho column, in-matrix time column
% (empty if time is a separate variable), and a human layout label.
tcol = []; timecol = [];
if ~isempty(vn)
    names = strtrim(cellfun(@(x) char(string(x)), vn(:)', 'uni', 0));
    find1 = @(n) find(strcmpi(names, n), 1);
    it = find1('Time'); if ~isempty(it); timecol = it; end
    raw = {'Fx1','Fx2','Fy1','Fy2','Fz1','Fz2','Fz3','Fz4'};
    fcols = [];
    for k = 1:numel(raw); c = find1(raw{k}); if ~isempty(c); fcols(end+1) = c; end %#ok<AGROW>
    end
    it2 = find(strncmpi(names, 'Tacho', 5), 1); if ~isempty(it2); tcol = it2; end
    if numel(names) == 13
        layout = 'v0.1';
    elseif isempty(tcol) && numel(fcols) < 8
        layout = 'v0.9-truncated';
    else
        layout = 'v1.0';
    end
    return;
end
% no VariableNames -> infer from version / variable name
if strcmp(dvar, 'data')            % v0.5: [8 raw, tacho], time in `timestamps`
    fcols = 1:8; tcol = 9; timecol = []; layout = 'v0.5';
elseif ver >= 1.0
    fcols = 2:9; tcol = 10; timecol = 1; layout = 'v1.0(inferred)';
else                               % v0.1: [time, Fx Fy Fz, 8 raw, tacho]
    fcols = 5:12; tcol = 13; timecol = 1; layout = 'v0.1(inferred)';
end
end

% --------------------------------------------------------------------
function ch = force_channels(vn, fcols)
% One descriptor per stored raw force column.
axes = containers.Map({'Fx1','Fx2','Fy1','Fy2','Fz1','Fz2','Fz3','Fz4'}, ...
                      {'x','x','y','y','z','z','z','z'});
if ~isempty(vn)
    names = strtrim(cellfun(@(x) char(string(x)), vn(:)', 'uni', 0));
    nm = names(fcols);
else
    all8 = {'Fx1','Fx2','Fy1','Fy2','Fz1','Fz2','Fz3','Fz4'};
    nm = all8(1:numel(fcols));
end
ch = repmat(struct('name','','role','force_raw','axis','','unit','N', ...
    'bits',NaN,'device','','sensitivity',NaN,'physical_range',NaN,'derived',false), ...
    1, numel(nm));
for k = 1:numel(nm)
    ch(k).name = nm{k};
    if isKey(axes, nm{k}); ch(k).axis = axes(nm{k}); end
end
end

% --------------------------------------------------------------------
function s = stream_struct(source, device, rate, N, dvar, tvar, channels)
s = struct('source', source, 'device', {device}, 'device_index', [], ...
    'measurement_type', '', 'rate_hz', rate, 'rate_limits', [], 'gain', NaN, ...
    'n_samples', N, 'data_var', dvar, 'time_var', tvar, ...
    'amp_settings_var', '', 'channels', channels);
end

% --------------------------------------------------------------------
function c = completeness(vn, fcols, hasTacho)
c = struct('force_corners_present', numel(fcols), 'tacho_present', hasTacho, ...
    'fz_full', numel(fcols) >= 8, 'rpm_available', hasTacho, 'missing', {{}});
miss = {};
if numel(fcols) < 8; miss{end+1} = 'Fz3/Fz4 (or other corners)'; end
if ~hasTacho; miss{end+1} = 'Tacho'; end
c.missing = miss;
end

function d = getdev(meta, field)
d = {};
if isfield(meta, field)
    v = meta.(field);
    if isfield(v, 'Device'); d = v.Device;
    elseif isfield(v, 'Devices'); d = v.Devices; end
end
end

function v = getnum(meta, field, dflt)
v = dflt;
if isfield(meta, field) && isnumeric(meta.(field)) && ~isempty(meta.(field))
    v = double(meta.(field)(1));
end
end

function v = getnested(meta, path, dflt)
v = meta;
for k = 1:numel(path)
    if isstruct(v) && isfield(v, path{k}); v = v.(path{k}); else; v = dflt; return; end
end
if isnumeric(v) && ~isempty(v); v = double(v(1)); else; v = dflt; end
end

function tf = is_v73(pth)
tf = false; fid = fopen(pth, 'r'); if fid < 0; return; end
c = onCleanup(@() fclose(fid));
hdr = fread(fid, 128, '*char')';
tf = contains(hdr, 'MATLAB 7.3');
end

function out = ternary(c, a, b); if c; out = a; else; out = b; end; end
