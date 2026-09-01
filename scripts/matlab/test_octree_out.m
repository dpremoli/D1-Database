function test_octree_out()
% Regression test for the octree_out + live_cache.bin combination the Diagnostics Workbench's
% diag handler (process_diag_row, scripts/force_orchestrator.py) needs from a SINGLE
% process_force call: the raw-spiral octree emit (cloud.bin) AND the dense live cache
% (live_cache.bin), together. octree_out used to `return` right after writing cloud.bin,
% which meant run_analysis never reached its own `summary = struct(...)` assignment when
% octree_out was set -- calling code that also expected live_cache.bin got neither the file
% nor a clean error, just MATLAB's own generic "unassignedOutputs" error and a status='error'
% summary.json with that unhelpful message, not the real cause.
%
% Run: matlab -batch "addpath('scripts/matlab'); test_octree_out"
% Errors (non-zero exit) on any failed assertion; prints PASS lines otherwise.

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

octp = fullfile(tmp, 'cloud.bin');
process_force(matp, tmp, struct('octree_out', octp, 'live_cache_points', 5000000));

% The regression: both artifacts must exist from this ONE call, and summary.json must report
% success, not the swallowed unassignedOutputs error.
assert(exist(octp, 'file') == 2, 'octree cloud.bin not written');
cachep = fullfile(tmp, 'live_cache.bin');
assert(exist(cachep, 'file') == 2, 'live_cache.bin not written alongside octree_out');

summp = fullfile(tmp, 'summary.json');
assert(exist(summp, 'file') == 2, 'summary.json not written');
summ = jsondecode(fileread(summp));
assert(strcmp(summ.status, 'done'), 'summary.json status=%s (expected done): %s', summ.status, summ.message);

% octree_out must still skip the FRM PNG rendering (that's what "skip_frm_png" means, and
% what the ORIGINAL early return was actually for) -- octree/diag callers never use them, and
% rendering three figures per file is wasted work at the scale the diag handler runs at.
assert(exist(fullfile(tmp, 'frm_Fx.png'), 'file') == 0, 'octree_out mode must skip FRM PNGs');

% cloud.bin (D1OC) and live_cache.bin (D1LC) must be index-aligned: process_diag_row reads
% both and treats a length mismatch as fatal (see force_orchestrator.py's process_diag_row).
fid = fopen(octp, 'r', 'l');
octmagic = fread(fid, 1, 'uint32'); octN = fread(fid, 1, 'uint32');
fclose(fid);
assert(octmagic == hex2dec('44314F43'), 'bad D1OC magic');

fid = fopen(cachep, 'r', 'l');
cachemagic = fread(fid, 1, 'uint32'); cachever = fread(fid, 1, 'uint32'); cacheN = fread(fid, 1, 'uint32'); %#ok<NASGU>
fclose(fid);
assert(cachemagic == hex2dec('44314C43'), 'bad D1LC magic');
assert(octN == cacheN, 'cloud.bin (%d pts) and live_cache.bin (%d pts) length mismatch', octN, cacheN);

fprintf('PASS octree_out + live_cache.bin: N=%d, status=%s\n', octN, summ.status);
fprintf('ALL OCTREE_OUT TESTS PASSED\n');
end
