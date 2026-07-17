function process_force(matpath, outdir, opts)
% PROCESS_FORCE  Read-only ABFPA-faithful force processing for a machining .mat.
%
%   process_force(MATPATH, OUTDIR, OPTS) reads the dynamometer force file at
%   MATPATH (an archive .mat, read strictly read-only) and writes to OUTDIR:
%       summary.json  scalar metrics + cut parameters (+ status)
%       series.json   downsampled min/max envelope of Fx/Fy/Fz/RPM for interactive plots
%       fft.json      per-axis amplitude spectrum (0..Nyquist)
%       frm_Fx/Fy/Fz.png  FRM spiral fingerprints, one per axis
%       live_cache.bin    medium-res decimated point cloud (t/Fx/Fy/Fz/rpm/revs_cum)
%                         for the browser's Live mode — recomputes the FRM client-side
%                         for any crop/Feed/Diameter/RPM without re-reading the archive
%   On any failure it still writes summary.json with status="error" and a message,
%   so the host orchestrator can record the outcome without parsing stderr.
%
%   OPTS (all optional; struct fields, admin-configurable via the crawler):
%       series_points   points per downsampled force/RPM envelope (default 3000)
%       fft_points      points per FFT spectrum, full Nyquist range (default 3000)
%       frm_downsample_step  FRM point-cloud stride: keep every Nth sample,
%                            data(1:N:end) (default 5; 1 = full density)
%       frm_dpi         exportgraphics Resolution for the FRM PNGs (default 300)
%       live_cache_points  target point count per axis in live_cache.bin (default 250000)
%       pulses_per_rev  tacho pulses per spindle revolution (default 1)
%
%   Channel/geometry logic mirrors ABetterFactoryPlusApp.LoadFile exactly:
%     v1.0: DATA = [t=col1, SumDyno(cols2:9), tacho=col10]
%     v0.5: DATA = [timestamps, SumDyno(cols1:8), tacho=col9]     (lowercase 'data')
%     v0.1: DATA = [t=col1, Fx=col2, Fy=col3, Fz=col4, tacho=col13] (uppercase 'DATA')
%   SumDyno: Fx=ch1+ch2, Fy=ch3+ch4, Fz=ch5+ch6+ch7+ch8.
%   The gain is NOT re-applied on load (the saved data is already post-gain); we
%   only surface metadata.Dyno.Gain so a gain of 1 (uncalibrated) is visible.
%
%   NEVER opens MATPATH writable and never writes back to it.

if nargin < 2
    error('process_force:args', 'usage: process_force(matpath, outdir, opts)');
end
if nargin < 3 || isempty(opts); opts = struct(); end
opts = withdefault(opts, 'series_points', 3000);
opts = withdefault(opts, 'fft_points', 3000);
opts = withdefault(opts, 'frm_downsample_step', 5);
opts = withdefault(opts, 'frm_dpi', 300);
opts = withdefault(opts, 'live_cache_points', 5000000);   % cache the cut window ~1:1 up to 5M (>5M -> octree)
opts = withdefault(opts, 'pulses_per_rev', 1);
opts = withdefault(opts, 'inner_diam', 0);   % donut/diaphragm inner diameter (mm); 0 = solid disc
opts = withdefault(opts, 'outer_diam', 0);   % outer-diameter override (mm); 0 = use metadata CutDiameter
if ~exist(outdir, 'dir'); mkdir(outdir); end

summary = struct('status', 'error', 'message', '', 'source', matpath);
try
    summary = run_analysis(matpath, outdir, opts);
catch ME
    summary.status  = 'error';
    summary.message = sprintf('%s: %s', ME.identifier, ME.message);
    fprintf(2, 'process_force FAILED: %s\n', summary.message);
end
writejson(fullfile(outdir, 'summary.json'), summary);
fprintf('STATUS=%s\n', summary.status);
end

function opts = withdefault(opts, name, default)
if ~isfield(opts, name) || isempty(opts.(name)); opts.(name) = default; end
end

% ===================================================================== core
function summary = run_analysis(matpath, outdir, opts)
fprintf('READ-ONLY processing: %s\n', matpath);
mf   = matfile(matpath);          % read-only (no 'Writable')
vars = who(mf);

ts = [];
if ismember('data', vars)         % lowercase -> v0.5 layout
    D = mf.data; ts = mf.timestamps; ver = 0.5;
elseif ismember('DATA', vars)     % uppercase -> v0.1 layout
    D = mf.DATA; ver = 0.1;
else
    error('process_force:novar', 'no data/DATA variable in file');
end

meta = struct();
if ismember('metadata', vars); meta = mf.metadata; end
if isfield(meta, 'fileVersion'); ver = double(meta.fileVersion); end

Fs      = getnum(meta, 'Rate', 25600);
Feed    = getnum(meta, 'Feed', 0.1);
Diam    = getnum(meta, 'CutDiameter', 80);
if opts.outer_diam > 0; Diam = opts.outer_diam; end   % per-op override (metadata sometimes wrong)
SurfSpd = getnum(meta, 'SurfaceSpeed', NaN);
DoC     = getnum(meta, 'DepthOfCut', NaN);
MaxRPM  = getnum(meta, 'MaxRPM', 1000);
gain    = getnested(meta, {'Dyno', 'Gain'}, NaN);
trigTime = getdatetime(meta, 'TriggerTime');
fprintf('  version=%.2f  Fs=%g  Feed=%g  Diam=%g  gain=%s  size=%s\n', ...
    ver, Fs, Feed, Diam, num2str(gain), mat2str(size(D)));

% ---- channels per version (mirrors LoadFile) ----
if ver >= 1.0
    forces = sumdyno(D(:, 2:9)); tacho = D(:, 10); t = D(:, 1);
elseif ver >= 0.5
    forces = sumdyno(D(:, 1:8)); tacho = D(:, 9);  t = ts(:);
else                              % v0.1: forces already single columns
    forces = D(:, 2:4);          tacho = D(:, 13); t = D(:, 1);
end
if isempty(t) || numel(t) ~= size(forces, 1); t = (0:size(forces,1)-1)' / Fs; end
Fx = double(forces(:,1)); Fy = double(forces(:,2)); Fz = double(forces(:,3));
N  = numel(Fz);

% ---- RPM from tacho (fallback: MaxRPM constant) ----
%   rpm_raw is at PulsesPerRev=1 (raw pulse-edge rate) — it alone feeds
%   revs_cum below, keeping the live cache's geometry PPR-agnostic so the
%   browser can apply any divisor to it interactively. `rpm` (the real,
%   per-op-corrected rate) feeds everything else: series.json's RPM envelope,
%   the FRM PNG geometry, and mean_rpm. FitType is linear (not smooth).
try
    rpm_raw = tachorpm(double(tacho), Fs, 'FitType', 'linear');
    rpm_raw = interp1(linspace(0,1,numel(rpm_raw))', rpm_raw(:), linspace(0,1,N)', 'linear', 'extrap');
catch ME
    fprintf('  tachorpm failed (%s); using MaxRPM=%g constant\n', ME.message, MaxRPM);
    rpm_raw = ones(N,1) * MaxRPM;
end
rpm = rpm_raw / opts.pulses_per_rev;

% ---- downsampled envelope series (force axes + RPM, for the interactive plots) ----
sp = opts.series_points;
series = struct('t_range', [t(1) t(end)], 'n_raw', N, ...
    'Fx', envelope_minmax(t, Fx, sp), ...
    'Fy', envelope_minmax(t, Fy, sp), ...
    'Fz', envelope_minmax(t, Fz, sp), ...
    'RPM', envelope_minmax(t, rpm, sp));
writejson(fullfile(outdir, 'series.json'), series);

% ---- per-axis amplitude spectrum ----
fftout = struct('Fx', spec(Fx, Fs, opts.fft_points), 'Fy', spec(Fy, Fs, opts.fft_points), ...
                'Fz', spec(Fz, Fs, opts.fft_points));
writejson(fullfile(outdir, 'fft.json'), fftout);

% ---- cut-start via findchangepts on Fz (ABFPA autocrop, downsample 100) ----
acds = 100;
try
    cp = findchangepts(Fz(1:acds:end), 'Statistic', 'mean');
    cutstart = max(1, min(cp) * acds);
catch
    cutstart = 1;                 % no clear engagement -> keep whole signal
end

% ---- FRM spiral fingerprint, built once from the cut region (geometry is
%      axis-independent; one clean PNG per force axis, coloured by that axis) ----
rpm_c = rpm(cutstart:end);
dt      = 1/Fs;                   % full-resolution integral (finer than app's downsampled dt)
ang_inc = rpm_c(2:end) * 2*pi/60 * dt;
rho_inc = -Feed * rpm_c(2:end) / 60 * dt;
theta   = wrapTo2Pi(cumsum([0; ang_inc]));
rho     = cumsum([Diam/2; rho_inc]);
inner_r = opts.inner_diam / 2;   % donut/diaphragm discs stop at the inner radius, not 0
cutend  = find(rho < inner_r, 1, 'first'); if isempty(cutend); cutend = numel(rho); end
theta   = theta(1:cutend); rho = rho(1:cutend);
step    = max(1, round(opts.frm_downsample_step));   % direct stride: data(1:step:end)
[xx, yy] = pol2cart(theta(1:step:end), rho(1:step:end));
abs_cut_end = cutstart + cutend - 1;

[~, stem] = fileparts(matpath);          % operation code (file stem) for the subtitle
axes_cut = {Fx(cutstart:cutstart+cutend-1), Fy(cutstart:cutstart+cutend-1), Fz(cutstart:cutstart+cutend-1)};
axes_name = {'Fx', 'Fy', 'Fz'};

% ---- viewport render request (Phase 1c): re-render ONLY the requested viewport at
%      FULL resolution (no stride) with the exact same styling as the canonical FRM
%      PNGs, write it to opts.viewport.out, then STOP (no cache/metrics/summary). The
%      force_orchestrator uploads that PNG as the "download this view" result. ----
if isfield(opts, 'viewport') && ~isempty(opts.viewport)
    vp = opts.viewport;
    kk = find(strcmp(vp.axis, axes_name), 1); if isempty(kk); kk = 3; end
    [vx, vy] = pol2cart(theta, rho);                 % full resolution — every point
    vcc = axes_cut{kk};
    inb = vx >= vp.xmin & vx <= vp.xmax & vy >= vp.ymin & vy <= vp.ymax;
    vx = vx(inb); vy = vy(inb); vcc = vcc(inb);
    fig = figure('Visible','off','Position',[0 0 1120 1000],'Color','w');
    ax  = axes(fig);                                          %#ok<LAXES>
    scatter(ax, vx, vy, 1, vcc, '.');
    axis(ax, 'equal');
    xlim(ax, [vp.xmin vp.xmax]); ylim(ax, [vp.ymin vp.ymax]);
    box(ax, 'on'); ax.Layer = 'top';
    set(ax, 'FontName', 'Times New Roman', 'FontSize', 15, ...
            'GridColor', [0.35 0.35 0.35], 'GridAlpha', 0.28, ...
            'MinorGridColor', [0.55 0.55 0.55], 'MinorGridAlpha', 0.15, ...
            'MinorGridLineStyle', ':');
    grid(ax, 'on'); grid(ax, 'minor');
    xlabel(ax, '\itx\rm (mm)'); ylabel(ax, '\ity\rm (mm)');
    if strcmpi(char(vp.colormap), 'grayscale'); colormap(ax, flipud(gray)); else; colormap(ax, viridis); end
    if isfield(vp,'cmin') && ~isempty(vp.cmin) && isfield(vp,'cmax') && ~isempty(vp.cmax) && vp.cmax > vp.cmin
        clim(ax, [vp.cmin vp.cmax]);
    elseif ~isempty(vcc)
        lim = prctile(vcc, [1 99]); if lim(2) > lim(1); clim(ax, lim); end
    end
    cb = colorbar(ax); cb.Label.String = [vp.axis ' (N)'];
    cb.Label.FontName = 'Times New Roman'; cb.Label.FontAngle = 'italic';
    ttl = title(ax, ['FRM plot in ' vp.axis ' direction']);
    set(ttl, 'FontAngle','normal','FontWeight','bold','FontName','Times New Roman','FontSize',21,'Units','normalized');
    ttl.Position(2) = ttl.Position(2) + 0.055;
    st = subtitle(ax, stem, 'Interpreter', 'none');
    set(st, 'Color',[0.45 0.45 0.45],'FontName','Times New Roman','FontSize',15,'Units','normalized');
    st.Position(2) = st.Position(2) + 0.035;
    exportgraphics(fig, vp.out, 'Resolution', opts.frm_dpi);
    close(fig);
    return;                                          % viewport-only: skip full processing
end

[xx0, yy0] = pol2cart(theta, rho);               % full-resolution spiral (shared by octree/grid emit)

% ---- octree emit (Phase 2): dump the FULL-resolution FRM cloud (x,y + all three
%      force axes) as a little-endian binary for the host to convert to a Potree
%      octree (LAS -> PotreeConverter). No stride: every cut-window sample. Then STOP.
%      Format: uint32 magic 0x44314F43 'D1OC', uint32 N, then float32 x,y,Fx,Fy,Fz [N].
if isfield(opts, 'octree_out') && ~isempty(opts.octree_out)
    ox = xx0; oy = yy0;                          % full resolution (shared)
    ofx = axes_cut{1}; ofy = axes_cut{2}; ofz = axes_cut{3};
    Noc = numel(ox);
    fid = fopen(char(opts.octree_out), 'w', 'l');
    if fid < 0; error('process_force:octree', 'cannot open %s', opts.octree_out); end
    cleaner = onCleanup(@() fclose(fid));
    fwrite(fid, uint32(hex2dec('44314F43')), 'uint32');
    fwrite(fid, uint32(Noc), 'uint32');
    fwrite(fid, single(ox(:)),  'single');
    fwrite(fid, single(oy(:)),  'single');
    fwrite(fid, single(ofx(:)), 'single');
    fwrite(fid, single(ofy(:)), 'single');
    fwrite(fid, single(ofz(:)), 'single');
    clear cleaner;                                   % flush+close now
    return;                                          % octree-only: skip full processing
end

% ---- interpolated-grid emit: interpolate the FULL-resolution spiral onto a fine N×N grid
%      (splat/GPU or natural), compute a hold-out-arms fidelity number, and dump the kept
%      in-support cells as a little-endian D1GR binary for the host to octree-convert. Then STOP.
%      Format: uint32 magic 0x44314752 'D1GR', uint32 N, float32 fidelity, arm_ratio, cell_mm,
%      then float32 x,y,Fx,Fy,Fz [N].
if isfield(opts, 'grid_out') && ~isempty(opts.grid_out)
    g = struct('n', 2048, 'method', 'splat', 'cv_arm_step', 10);
    if isfield(opts, 'grid') && isstruct(opts.grid)
        fn = fieldnames(opts.grid);
        for ii = 1:numel(fn); g.(fn{ii}) = opts.grid.(fn{ii}); end
    end
    theta_cum = cumsum([0; ang_inc]);            % unwrapped cumulative angle (for arm indexing)
    theta_cum = theta_cum(1:cutend);
    gfx = axes_cut{1}; gfy = axes_cut{2}; gfz = axes_cut{3};
    [gx, gy, gFx, gFy, gFz, cellmm] = frm_grid_interp(xx0, yy0, gfx, gfy, gfz, g.n, g.method);
    [fidelity, arm_ratio] = frm_grid_fidelity(xx0, yy0, theta_cum, gfx, gfy, gfz, g.n, g.method, cellmm, g.cv_arm_step);
    Ng = numel(gx);
    fid = fopen(char(opts.grid_out), 'w', 'l');
    if fid < 0; error('process_force:grid', 'cannot open %s', opts.grid_out); end
    cleaner = onCleanup(@() fclose(fid));
    fwrite(fid, uint32(hex2dec('44314752')), 'uint32');
    fwrite(fid, uint32(Ng), 'uint32');
    fwrite(fid, single(fidelity), 'single');       % NaN -> reader maps to null
    fwrite(fid, single(arm_ratio), 'single');
    fwrite(fid, single(cellmm), 'single');
    fwrite(fid, single(gx(:)),  'single');
    fwrite(fid, single(gy(:)),  'single');
    fwrite(fid, single(gFx(:)), 'single');
    fwrite(fid, single(gFy(:)), 'single');
    fwrite(fid, single(gFz(:)), 'single');
    clear cleaner;                                  % flush+close now
    return;                                         % grid-only: skip full processing
end

for k = 1:3
    cc  = axes_cut{k}(1:step:end);
    fig = figure('Visible','off','Position',[0 0 1120 1000],'Color','w');
    ax  = axes(fig);                                          %#ok<LAXES>
    scatter(ax, xx, yy, 1, cc, '.');          % Markersize ~1, like the app's pcshow
    axis(ax, 'equal'); axis(ax, 'tight');
    box(ax, 'on'); ax.Layer = 'top';
    set(ax, 'FontName', 'Times New Roman', 'FontSize', 15, ...
            'GridColor', [0.35 0.35 0.35], 'GridAlpha', 0.28, ...
            'MinorGridColor', [0.55 0.55 0.55], 'MinorGridAlpha', 0.15, ...
            'MinorGridLineStyle', ':');
    grid(ax, 'on'); grid(ax, 'minor');
    xlabel(ax, '\itx\rm (mm)'); ylabel(ax, '\ity\rm (mm)');

    colormap(ax, viridis);
    lim = prctile(cc, [1 99]); if lim(2) <= lim(1); lim = [min(cc) max(cc)]; end
    if lim(2) > lim(1); clim(ax, lim); end
    cb = colorbar(ax);
    cb.Label.String = [axes_name{k} ' (N)'];
    cb.Label.FontName = 'Times New Roman'; cb.Label.FontAngle = 'italic';
    cb.Ticks = unique(round([lim(1), cb.Ticks(:).', lim(2)], 2));

    ttl = title(ax, ['FRM plot in ' axes_name{k} ' direction']);   % not 't' — 't' is the time vector
    set(ttl, 'FontAngle', 'normal', 'FontWeight', 'bold', 'FontName', 'Times New Roman', ...
           'FontSize', 21, 'Units', 'normalized');
    ttl.Position(2) = ttl.Position(2) + 0.055;         % lift title above the plot
    st = subtitle(ax, stem, 'Interpreter', 'none');
    set(st, 'Color', [0.45 0.45 0.45], 'FontName', 'Times New Roman', ...
            'FontSize', 15, 'Units', 'normalized');
    st.Position(2) = st.Position(2) + 0.035;        % lift subtitle, keep gap to plot

    exportgraphics(fig, fullfile(outdir, ['frm_' axes_name{k} '.png']), 'Resolution', opts.frm_dpi);
    close(fig);
end

% ---- live cache: decimated point cloud for the browser's Live mode ----
%   revs_cum (cumulative revolutions from index 1) is integrated at FULL resolution
%   from rpm_raw (PulsesPerRev=1) then decimated — since it is smooth + monotonic,
%   decimation is lossless for client-side reconstruction, and staying PPR-agnostic
%   lets the browser divide by ANY pulses-per-rev interactively. The client rebuilds
%   theta/rho for ANY crop-start cs / Feed / Diam / PPR via:
%   r = (revs_cum(i)-revs_cum(cs))/PPR;  theta = wrapTo2Pi(2*pi*r);
%   rho = Diam/2 - Feed*r.  (An RPM override instead uses r = RPM/60 * t.)
revs_cum = cumsum([0; rpm_raw(2:end) / 60 * dt]);         % turns elapsed at each sample (raw, PPR=1)
write_live_cache(fullfile(outdir, 'live_cache.bin'), opts.live_cache_points, ...
    Fs, Feed, Diam, cutstart, abs_cut_end, t, Fx, Fy, Fz, rpm, revs_cum);

% ---- summary ----
summary = struct( ...
    'status','done', 'message','', 'source',matpath, ...
    'version',ver, 'sample_rate',Fs, 'feed',Feed, 'cut_diameter',Diam, ...
    'surface_speed',SurfSpd, 'depth_of_cut',DoC, 'max_rpm',MaxRPM, 'dyno_gain',gain, ...
    'trigger_time',trigTime, ...
    'n_raw',N, 'cut_start_idx',cutstart, 'cut_end_idx',abs_cut_end, ...
    'peak_fx',max(abs(Fx)), 'peak_fy',max(abs(Fy)), 'peak_fz',max(abs(Fz)), ...
    'mean_rpm',mean(rpm,'omitnan'), 'pulses_per_rev',opts.pulses_per_rev);
disp(summary);
fprintf('DONE. Outputs in %s\n', outdir);
end

% ================================================================== helpers
function F = sumdyno(d)
d = double(d);
F = [d(:,1)+d(:,2), d(:,3)+d(:,4), d(:,5)+d(:,6)+d(:,7)+d(:,8)];
end

function v = getnum(meta, field, default)
v = default;
if isstruct(meta) && isfield(meta, field)
    x = meta.(field);
    if isnumeric(x) && ~isempty(x); v = double(x(1));
    elseif ischar(x) || isstring(x); n = str2double(x); if ~isnan(n); v = n; end
    end
end
end

function v = getnested(meta, path, default)
v = meta;
for k = 1:numel(path)
    if isstruct(v) && isfield(v, path{k}); v = v.(path{k}); else; v = default; return; end
end
if isnumeric(v) && ~isempty(v); v = double(v(1));
elseif ischar(v) || isstring(v); n = str2double(v); if ~isnan(n); v = n; else; v = default; end
else; v = default; end
end

function v = getdatetime(meta, field)
% Returns an ISO-8601 string ('' if absent/unparseable). TriggerTime in the
% archive shows up as a MATLAB datetime, a datenum double, or a date string
% depending on the app version that wrote the file, so all three are handled.
v = '';
if ~(isstruct(meta) && isfield(meta, field)); return; end
x = meta.(field);
try
    if isa(x, 'datetime')
        dt = x(1);
    elseif isnumeric(x) && ~isempty(x)
        dt = datetime(x(1), 'ConvertFrom', 'datenum');
    elseif ischar(x) || isstring(x)
        dt = datetime(x);            % auto-detects the format
    else
        return;
    end
    v = char(string(dt, 'yyyy-MM-dd''T''HH:mm:ss'));
catch
    if ischar(x) || isstring(x); v = char(x); end   % last resort: pass the raw string through
end
end

function e = envelope_minmax(t, y, nbuckets)
N = numel(y);
if N <= nbuckets*2
    e = struct('t', t(:)', 'min', y(:)', 'max', y(:)'); return;
end
edges = round(linspace(1, N+1, nbuckets+1));
tt = zeros(1,nbuckets); ymin = zeros(1,nbuckets); ymax = zeros(1,nbuckets);
for i = 1:nbuckets
    a = edges(i); b = edges(i+1)-1; seg = y(a:b);
    tt(i) = t(round((a+b)/2)); ymin(i) = min(seg); ymax(i) = max(seg);
end
e = struct('t', tt, 'min', ymin, 'max', ymax);
end

function s = spec(y, Fs, fft_points)
try
    [p, f] = pspectrum(double(y), Fs);   % f spans 0 .. Fs/2 (Nyquist) by default
    amp = sqrt(p);
    step = max(1, floor(numel(f)/fft_points));  % keep full Nyquist range
    s = struct('f', f(1:step:end)', 'amp', amp(1:step:end)');
catch
    s = struct('f', [], 'amp', []);
end
end

function writejson(fname, s)
fid = fopen(fname, 'w');
fwrite(fid, jsonencode(s));
fclose(fid);
end

function write_live_cache(fname, target, Fs, Feed, Diam, cutstart, cutend, t, Fx, Fy, Fz, rpm, revs)
% Little-endian binary point-cloud cache. Header (32 bytes) then six float32[N]
% arrays. Layout MUST match the client parser in LivePlot.vue:
%   uint32 magic=0x44314C43('D1LC'), uint32 version=1, uint32 N, float32 Fs,
%   float32 orig_feed, float32 orig_diam, float32 orig_cut_start_sec,
%   float32 orig_cut_end_sec, then t,Fx,Fy,Fz,rpm,revs_cum (each float32[N]).
% Cache ONLY the cut (engagement) window at up to `target` points. The FRM spiral
% uses just this window, so budgeting the whole (mostly idle) signal wasted ~90%+ of
% the points on the region the fingerprint never draws — e.g. a 1M cache over a 30M
% signal left only ~62k points inside a 1.9M-sample cut. Caching the window instead
% gives FULL resolution for windows <= target (continuous full-res below the cap).
% Tradeoff: Live-mode crop is bounded to the analysed window (the sensible range).
win  = cutstart:cutend;
tt = t(win); fxx = Fx(win); fyy = Fy(win); fzz = Fz(win); rr = rpm(win); rv = revs(win);
N0   = numel(tt);
step = max(1, ceil(N0 / max(1, target)));      % 1:1 when the window fits in `target`
idx  = 1:step:N0;
N    = numel(idx);
cs_sec = (cutstart - 1) / Fs;                  % window start = cache start
ce_sec = (cutend   - 1) / Fs;                  % window end   = cache end

fid = fopen(fname, 'w', 'l');                   % 'l' = force little-endian
if fid < 0; error('process_force:cache', 'cannot open %s', fname); end
c = onCleanup(@() fclose(fid));
fwrite(fid, uint32(hex2dec('44314C43')), 'uint32');
fwrite(fid, uint32(1),  'uint32');
fwrite(fid, uint32(N),  'uint32');
fwrite(fid, single(Fs), 'single');
fwrite(fid, single(Feed), 'single');
fwrite(fid, single(Diam), 'single');
fwrite(fid, single(cs_sec), 'single');
fwrite(fid, single(ce_sec), 'single');
fwrite(fid, single(tt(idx)),  'single');
fwrite(fid, single(fxx(idx)), 'single');
fwrite(fid, single(fyy(idx)), 'single');
fwrite(fid, single(fzz(idx)), 'single');
fwrite(fid, single(rr(idx)),  'single');
fwrite(fid, single(rv(idx)),  'single');
end
