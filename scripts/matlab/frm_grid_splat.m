function [gx, gy, gFx, gFy, gFz] = frm_grid_splat(xx, yy, cFx, cFy, cFz, x0, y0, cell, N)
% Gaussian splat via scatter-then-separable-blur. Scatter each point's value + a unit
% weight into its nearest cell (accumarray), then convolve both with a separable Gaussian
% (sigma ~0.7 cell). value = blur(sum)/blur(weight). Keep cells with weight above eps (a
% data-support mask). The conv is offloaded to the GPU when one is present. Returns kept
% cell centres + interpolated forces as column vectors.
ix = min(N, max(1, floor((xx - x0)/cell) + 1));
iy = min(N, max(1, floor((yy - y0)/cell) + 1));
lin = sub2ind([N N], iy, ix);
W  = accumarray(lin, 1,           [N*N 1]);
Sx = accumarray(lin, double(cFx), [N*N 1]);
Sy = accumarray(lin, double(cFy), [N*N 1]);
Sz = accumarray(lin, double(cFz), [N*N 1]);
W = reshape(W,[N N]); Sx = reshape(Sx,[N N]); Sy = reshape(Sy,[N N]); Sz = reshape(Sz,[N N]);

sigma = 0.7; r = ceil(3*sigma); k = exp(-((-r:r).^2)/(2*sigma^2)); k = k / sum(k);
useGpu = gpu_usable();       % a present-but-unsupported GPU falls back to CPU (identical output)
if useGpu
    W = gpuArray(W); Sx = gpuArray(Sx); Sy = gpuArray(Sy); Sz = gpuArray(Sz); k = gpuArray(k);
end
blur = @(A) conv2(k, k, A, 'same');
Wb = blur(W); Sxb = blur(Sx); Syb = blur(Sy); Szb = blur(Sz);
mask = Wb > 1e-6;
Vx = zeros(N,N,'like',Wb); Vy = Vx; Vz = Vx;
Vx(mask) = Sxb(mask)./Wb(mask);
Vy(mask) = Syb(mask)./Wb(mask);
Vz(mask) = Szb(mask)./Wb(mask);
if useGpu
    mask = gather(mask); Vx = gather(Vx); Vy = gather(Vy); Vz = gather(Vz);
end
[iyk, ixk] = find(mask);
gx = x0 + (ixk - 0.5) * cell;
gy = y0 + (iyk - 0.5) * cell;
idx = sub2ind([N N], iyk, ixk);
gFx = Vx(idx); gFy = Vy(idx); gFz = Vz(idx);
end

function tf = gpu_usable()
% True only if a GPU is present AND actually usable for gpuArray ops. Some devices
% (e.g. a compute-capability newer than the bundled CUDA supports) report a count but
% throw on first use; probe once and cache so we transparently fall back to the CPU.
persistent cached
if ~isempty(cached); tf = cached; return; end
tf = false;
try
    if gpuDeviceCount > 0
        t = gpuArray(single([1 2; 3 4]));      % force a real op
        t = conv2(single([1 1])/2, single([1 1])/2, t, 'same'); %#ok<NASGU>
        wait(gpuDevice);
        tf = true;
    end
catch
    tf = false;
end
cached = tf;
end

