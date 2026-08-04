function rep = upgrade_force_v05_to_v10(src, dst, varargin)
%UPGRADE_FORCE_V05_TO_V10  Restructure a v0.5 force capture into the v1.0 layout.
%
%   rep = upgrade_force_v05_to_v10(SRC, DST)
%   rep = upgrade_force_v05_to_v10(SRC, DST, 'ChunkRows', 5e6, 'DryRun', true)
%
% v0.5 stores a 9-column lowercase `data` plus a separate `timestamps` vector.
% v1.0 stores a 10-column uppercase `DATA` with time as column 1:
%
%   DATA = [ timestamps , data(:,1:8) , data(:,9) ]
%            Time         Fx1..Fz4      Tacho
%
% This is a pure column remap -- no resampling, no arithmetic, nothing discarded.
% Per docs/force-file-standards.md §6, `fileVersion` is only stamped once the
% matrix itself is in the target layout, and both happen in this one operation.
%
% The source file is opened read-only and never modified. Output is written to a
% new v7.3 file in row chunks, so multi-GB captures never load whole into memory.
%
% AmpSettings cannot be synthesised (it is a signed LabAmp export) -- pre-v1.0
% captures have no amplifier calibration and that gap is permanent.

p = inputParser;
p.addParameter('ChunkRows', 5e6, @isnumeric);
p.addParameter('DryRun', false, @islogical);
p.addParameter('Verify', true, @islogical);
p.parse(varargin{:});
opt = p.Results;

V10_NAMES = {'Time','Fx1','Fx2','Fy1','Fy2','Fz1','Fz2','Fz3','Fz4','Tacho (ai0)'};
CANON = {'SampleName','OpType','Operation','OperationType','TriggerTime','Rate', ...
         'CutDiameter','SurfaceSpeed','MaxRPM','Notes','Feed','DepthOfCut', ...
         'Insert','EdgeID','Machine','Tool','New_Edge','Swarf','SwarfID', ...
         'Coolant','fileVersion','Dyno','Stream1'};

rep = struct('src', string(src), 'dst', string(dst), 'status', "", 'note', "", ...
             'rows', NaN, 'cols_in', NaN, 'secs', NaN);
t0 = tic;

% ---- validate the source really is v0.5 ------------------------------------
mi   = matfile(src);
vars = who(mi);
if ~ismember('data', vars)
    rep.status = "SKIP"; rep.note = "no lowercase `data` variable (not v0.5)"; return;
end
if ismember('DATA', vars)
    rep.status = "SKIP"; rep.note = "already has uppercase DATA"; return;
end
if ~ismember('timestamps', vars)
    rep.status = "SKIP"; rep.note = "no `timestamps` variable"; return;
end

w  = whos(mi);
sd = w(strcmp({w.name}, 'data')).size;
st = w(strcmp({w.name}, 'timestamps')).size;
n  = sd(1); ncol = sd(2);
rep.rows = n; rep.cols_in = ncol;

if ncol ~= 9
    rep.status = "SKIP"; rep.note = sprintf("`data` has %d columns, expected 9", ncol); return;
end
if max(st) ~= n
    rep.status = "SKIP";
    rep.note = sprintf("timestamps length %d != data rows %d", max(st), n); return;
end

meta = struct();
if ismember('metadata', vars); meta = mi.metadata; end
if isfield(meta, 'fileVersion') && double(meta.fileVersion(1)) >= 1.0
    rep.status = "SKIP"; rep.note = "already declares fileVersion >= 1.0"; return;
end

if opt.DryRun
    rep.status = "DRYRUN";
    rep.note = sprintf("would write %d x 10 from %d x %d", n, n, ncol);
    rep.secs = toc(t0); return;
end

% ---- write the restructured matrix in chunks -------------------------------
if exist(dst, 'file'); delete(dst); end
d = fileparts(dst);
if ~isempty(d) && ~isfolder(d); mkdir(d); end

placeholder = 0;                                    %#ok<NASGU>
save(dst, 'placeholder', '-v7.3');
mo = matfile(dst, 'Writable', true);

step = max(1, floor(opt.ChunkRows));
for i = 1:step:n
    j = min(i + step - 1, n);
    blk = double(mi.data(i:j, 1:9));
    ts  = double(mi.timestamps(i:j, 1));
    mo.DATA(i:j, 1:10) = [ts, blk(:, 1:8), blk(:, 9)];
end

% ---- metadata: carry everything over, add the v1.0 declaration -------------
for k = 1:numel(CANON)
    f = CANON{k};
    if ~isfield(meta, f) && ~any(strcmp(f, {'Dyno','Stream1','fileVersion'}))
        meta.(f) = '';                              % the app defaults absent fields to ''
    end
end
meta.fileVersion = 1;
mo.metadata      = meta;
mo.VariableNames = V10_NAMES;
mo.upgraded_from = struct('layout', 'v0.5', 'source', string(src), ...
                          'when', string(datetime('now','Format','yyyy-MM-dd HH:mm:ss')), ...
                          'tool', 'upgrade_force_v05_to_v10');

clear mo
% remove the bootstrap variable now that real content exists
warning('off', 'MATLAB:save:sizeTooBigForMATFile');
mo = matfile(dst, 'Writable', true);
try; mo.placeholder = []; catch; end
clear mo

% ---- verify against the source --------------------------------------------
if opt.Verify
    mv = matfile(dst);
    wv = whos(mv);
    sv = wv(strcmp({wv.name}, 'DATA')).size;
    if ~isequal(sv, [n 10])
        rep.status = "FAIL"; rep.note = sprintf("output DATA is %s, expected [%d 10]", mat2str(sv), n);
        rep.secs = toc(t0); return;
    end
    probe = unique(round(linspace(1, n, min(2000, n))));
    A = double(mv.DATA(probe, 1:10));
    B = [double(mi.timestamps(probe, 1)), double(mi.data(probe, 1:8)), double(mi.data(probe, 9))];
    dmax = max(abs(A(:) - B(:)));
    if ~(dmax == 0)
        rep.status = "FAIL"; rep.note = sprintf("row check mismatch, max|diff|=%g", dmax);
        rep.secs = toc(t0); return;
    end
    rep.note = sprintf("verified %d probe rows, exact", numel(probe));
end

rep.status = "OK";
rep.secs   = toc(t0);
end
