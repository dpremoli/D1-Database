function test_grid_out()
% Standalone asserts for the grid interpolation + fidelity helpers. Run:
%   matlab -batch "addpath('scripts/matlab'); test_grid_out"
% Errors (non-zero exit) on any failed assertion; prints PASS lines otherwise.

rng(7);
% Synthetic spiral: rho shrinks, theta winds — same geometry as the FRM.
turns = 12; ppt = 400; nrev = turns*ppt;
th = linspace(0, turns*2*pi, nrev)';
rho = linspace(40, 2, nrev)';
[xx, yy] = pol2cart(mod(th,2*pi), rho);
% A smooth field so interpolation should reconstruct it well.
truef = @(x,y) 100 + 30*sin(x/6) + 20*cos(y/5);
cFx = truef(xx,yy); cFy = 0.5*cFx; cFz = 2*cFx;

for method = {'splat','natural'}
    m = method{1};
    [gx, gy, gFx, gFy, gFz, cell] = frm_grid_interp(xx, yy, cFx, cFy, cFz, 256, m);
    assert(~isempty(gx), '%s: empty grid', m);
    assert(isequal(size(gx), size(gFx)), '%s: length mismatch', m);
    assert(cell > 0, '%s: bad cell', m);
    assert(all(gx >= min(xx)-cell & gx <= max(xx)+cell), '%s: x out of bounds', m);
    % interpolated values must stay within the data range (no wild overshoot)
    assert(min(gFx) >= min(cFx)-1 && max(gFx) <= max(cFx)+1, '%s: Fx overshoot', m);

    [fid, ratio] = frm_grid_fidelity(xx, yy, th, cFx, cFy, cFz, 256, m, cell, 3);
    assert(fid >= 0 && fid <= 1, '%s: fidelity out of [0,1] (%g)', m, fid);
    assert(fid > 0.5, '%s: fidelity too low on smooth field (%g)', m, fid);
    assert(ratio > 0, '%s: arm_ratio not positive (%g)', m, ratio);
    fprintf('PASS %s: n=%d cell=%.3f fidelity=%.3f arm_ratio=%.3f\n', m, numel(gx), cell, fid, ratio);
end

% CPU/GPU splat agreement (only if a GPU is present)
if gpuDeviceCount > 0
    [~,~,a] = frm_grid_interp(xx, yy, cFx, cFy, cFz, 256, 'splat');   % GPU path taken internally
    assert(~isempty(a), 'gpu splat empty');
    fprintf('PASS gpu present; splat ran\n');
end

% ---- D1GR binary emit round-trip (build a tiny synthetic .mat, run process_force) ----
tmp = tempname; mkdir(tmp);
matp = fullfile(tmp, '10-AA-TEST-1-1-F1.mat');
Fs = 25600; n = 60000;
t = (0:n-1)'/Fs;
rpm = 1500*ones(n,1);
% v1.0 layout: [t, 8 dyno cols, tacho]
dyno = repmat(50*sin(t*3), 1, 8) + 5*randn(n,8);
tacho = sign(sin(2*pi*(rpm(1)/60).*t));   % crude pulse train (base MATLAB; no toolbox)
DATA = [t, dyno, tacho]; %#ok<NASGU>
metadata = struct('fileVersion',1.0,'Rate',Fs,'Feed',0.1,'CutDiameter',60,'MaxRPM',1500); %#ok<NASGU>
save(matp, 'DATA', 'metadata', '-v7');
outp = fullfile(tmp, 'grid.bin');
process_force(matp, tmp, struct('grid_out', outp, 'grid', struct('n', 512, 'method', 'splat', 'cv_arm_step', 10)));
assert(exist(outp,'file')==2, 'D1GR file not written');
fid = fopen(outp,'r','l'); hdr = fread(fid, 1, 'uint32'); Ncells = fread(fid, 1, 'uint32');
fidelity = fread(fid,1,'single'); armr = fread(fid,1,'single'); cellmm = fread(fid,1,'single');
body = fread(fid, Ncells*5, 'single'); fclose(fid);
assert(hdr == hex2dec('44314752'), 'bad D1GR magic');
assert(Ncells > 0, 'no cells emitted');
assert(numel(body) == Ncells*5, 'body length mismatch');
assert(cellmm > 0, 'bad cell_mm');
fprintf('PASS D1GR emit: N=%d fidelity=%.3f arm_ratio=%.3f cell=%.4f\n', Ncells, fidelity, armr, cellmm);

fprintf('ALL GRID TESTS PASSED\n');
end
