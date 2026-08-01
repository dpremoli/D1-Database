function test_filter_parity(dirpath)
% Parity harness (MATLAB side): read the shared fixture written by
% scripts/test_filter_parity.py, run frm_filters, write the result for comparison.
%   dirpath/parity_in.csv   columns fx,fy,fz (no header)
%   dirpath/chain.json      the filter chain
%   dirpath/meta.json       {"fs": ..., "mean_rpm": ...}
% Writes dirpath/out_ml.csv (fx,fy,fz).
X = readmatrix(fullfile(dirpath, 'parity_in.csv'));
meta = jsondecode(fileread(fullfile(dirpath, 'meta.json')));
chain = jsondecode(fileread(fullfile(dirpath, 'chain.json')));
[fx, fy, fz] = frm_filters(X(:,1), X(:,2), X(:,3), meta.fs, meta.mean_rpm, chain);
writematrix([fx fy fz], fullfile(dirpath, 'out_ml.csv'));
fprintf('PARITY: wrote %d rows\n', numel(fx));
end
