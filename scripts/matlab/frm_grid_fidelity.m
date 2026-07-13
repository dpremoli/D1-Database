function [fidelity, arm_ratio] = frm_grid_fidelity(xx, yy, theta_cum, cFx, cFy, cFz, N, method, cell, cv_arm_step)
% Hold-out-arms cross-validation. Arms = revolution index floor(theta_cum/2pi). Hold out
% every cv_arm_step-th arm; interpolate from the rest; predict at the held-out points; score
% nRMSE + fidelity on |F| = sqrt(Fx^2+Fy^2+Fz^2). arm_ratio = median arm spacing / cell.
arm = floor(theta_cum(:) / (2*pi));
arm = arm - min(arm);
narm = max(arm) + 1;
% median radial spacing between successive arms at matched angle ~ median |d rho| per turn.
rho = hypot(xx, yy);
arm_ratio = compute_arm_ratio(rho, arm, narm, cell);
if narm < 3
    fidelity = NaN; return;      % too few arms to hold any out
end
test = mod(arm, max(2, round(cv_arm_step))) == 0;
train = ~test;
if nnz(test) < 8 || nnz(train) < 32
    fidelity = NaN; return;
end
switch lower(method)
    case 'natural'
        px = predict_natural(xx(train), yy(train), cFx(train), xx(test), yy(test));
        py = predict_natural(xx(train), yy(train), cFy(train), xx(test), yy(test));
        pz = predict_natural(xx(train), yy(train), cFz(train), xx(test), yy(test));
    otherwise
        [px, py, pz] = predict_splat(xx(train), yy(train), cFx(train), cFy(train), cFz(train), ...
                                     xx(test), yy(test), cell, N);
end
ok = ~isnan(px) & ~isnan(py) & ~isnan(pz);
if nnz(ok) < 8; fidelity = NaN; return; end
predMag = sqrt(px(ok).^2 + py(ok).^2 + pz(ok).^2);
trueMag = sqrt(cFx(test).^2 + cFy(test).^2 + cFz(test).^2); trueMag = trueMag(ok);
rmse = sqrt(mean((predMag - trueMag).^2));
p = prctile(trueMag, [1 99]); rng_ = p(2) - p(1); if ~(rng_ > 0); rng_ = max(trueMag) - min(trueMag); end
if ~(rng_ > 0); fidelity = NaN; return; end
nrmse = rmse / rng_;
fidelity = min(1, max(0, 1 - nrmse));
end

function r = compute_arm_ratio(rho, arm, narm, cell)
% Median radial gap between consecutive arms (proxy for spiral pitch) divided by cell.
med = zeros(narm,1);
for a = 0:narm-1
    v = rho(arm == a);
    if ~isempty(v); med(a+1) = median(v); end
end
med = med(med > 0);
if numel(med) < 2; r = NaN; return; end
r = median(abs(diff(sort(med, 'descend')))) / cell;
if ~(r > 0); r = NaN; end
end

function v = predict_natural(xt, yt, ft, xq, yq)
f = scatteredInterpolant(xt, yt, double(ft), 'natural', 'none');
v = f(xq, yq);
end

function [px, py, pz] = predict_splat(xt, yt, fxt, fyt, fzt, xq, yq, cell, N)
% Build a splat grid from the training arms, then bilinearly sample it at the query points.
xmin = min([xt; xq]); ymin = min([yt; yq]);
x0 = xmin - cell; y0 = ymin - cell;
[gx, gy, gFx, gFy, gFz] = frm_grid_splat(xt, yt, fxt, fyt, fzt, x0, y0, cell, N); %#ok<ASGLU>
% Reassemble sparse grids to full for interpolation (griddata over kept centres).
px = griddata(gx, gy, gFx, xq, yq, 'linear');
py = griddata(gx, gy, gFy, xq, yq, 'linear');
pz = griddata(gx, gy, gFz, xq, yq, 'linear');
end
