function [gx, gy, gFx, gFy, gFz, cell] = frm_grid_interp(xx, yy, cFx, cFy, cFz, N, method)
% Interpolate scattered spiral points (xx,yy) with per-axis values onto an equal-aspect
% N×N grid; return the kept (data-supported / in-hull) cell centres and interpolated
% forces as column vectors, plus the cell spacing. method: 'splat' | 'natural'.
N = min(8192, max(16, round(N)));
xmin = min(xx); xmax = max(xx); ymin = min(yy); ymax = max(yy);
span = max(xmax - xmin, ymax - ymin);
if ~(span > 0); error('frm_grid:degenerate', 'zero-span spiral'); end
cell = span / N;
cx = (xmin + xmax)/2; cy = (ymin + ymax)/2;      % centre the equal-aspect box
x0 = cx - span/2; y0 = cy - span/2;              % lower-left of the square grid
xc = x0 + (0.5:N-0.5)' * cell;                   % cell-centre coordinates
yc = y0 + (0.5:N-0.5)' * cell;

switch lower(method)
    case 'natural'
        [gx, gy, gFx, gFy, gFz] = grid_natural(xx, yy, cFx, cFy, cFz, xc, yc);
    otherwise   % 'splat'
        [gx, gy, gFx, gFy, gFz] = frm_grid_splat(xx, yy, cFx, cFy, cFz, x0, y0, cell, N);
end
end

function [gx, gy, gFx, gFy, gFz] = grid_natural(xx, yy, cFx, cFy, cFz, xc, yc)
% Delaunay natural-neighbour interpolation (matches the manual MATLAB workflow). Keep only
% grid nodes inside the convex hull ('none' extrapolation -> NaN outside).
[GX, GY] = meshgrid(xc, yc);
fx = scatteredInterpolant(xx, yy, double(cFx), 'natural', 'none');
fy = scatteredInterpolant(xx, yy, double(cFy), 'natural', 'none');
fz = scatteredInterpolant(xx, yy, double(cFz), 'natural', 'none');
Vx = fx(GX, GY); Vy = fy(GX, GY); Vz = fz(GX, GY);
mask = ~isnan(Vx);
gx = GX(mask); gy = GY(mask);
gFx = Vx(mask); gFy = Vy(mask); gFz = Vz(mask);
end
