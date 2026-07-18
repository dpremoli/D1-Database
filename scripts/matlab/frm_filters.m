function [Fx, Fy, Fz, applied] = frm_filters(Fx, Fy, Fz, Fs, mean_rpm, chain)
% FRM_FILTERS  Apply the FRM signal-filter chain (bake-side twin of the filter-service).
%
%   [Fx,Fy,Fz,applied] = frm_filters(Fx,Fy,Fz,Fs,mean_rpm,chain) applies, in fixed
%   order, the stages enabled in CHAIN (a struct decoded from the op's filter_chain
%   JSON): despike (Hampel), detrend (dc | highpass), lowpass (Butterworth), notch
%   (IIR at harmonics of mean_rpm/60). All IIR stages are ZERO-PHASE (filtfilt) so
%   the FRM spiral geometry never phase-shifts.
%
%   MUST stay numerically in lock-step with plugins/filter-service/app/filters.py —
%   the parity test (test_filter_parity.m + test_parity.py) guards the pair.
applied = {};
nyq = Fs / 2;

% ---- despike (Hampel: sigma * 1.4826*MAD from the rolling median) ----
if stagen(chain, 'despike')
    w  = geti(chain.despike, 'window', 11);
    sg = getf(chain.despike, 'sigma', 5);
    half = floor(w/2);
    % hampel's DevianceFactor multiplies 1.4826*MAD, matching the python twin.
    Fx = hampel(Fx, half, sg); Fy = hampel(Fy, half, sg); Fz = hampel(Fz, half, sg);
    applied{end+1} = 'despike';
end

% ---- detrend ----
if stagen(chain, 'detrend')
    mode = 'highpass';
    if isfield(chain.detrend, 'mode'); mode = char(chain.detrend.mode); end
    if strcmp(mode, 'dc')
        Fx = Fx - mean(Fx); Fy = Fy - mean(Fy); Fz = Fz - mean(Fz);
        applied{end+1} = 'detrend-dc';
    else
        fc = getf(chain.detrend, 'cutoff_hz', 5);
        if fc > 0 && fc < nyq
            [z, p, k] = butter(2, fc/nyq, 'high');
            [sos, g] = zp2sos(z, p, k);
            Fx = filtfilt(sos, g, Fx); Fy = filtfilt(sos, g, Fy); Fz = filtfilt(sos, g, Fz);
            applied{end+1} = 'detrend-hp';
        end
    end
end

% ---- lowpass ----
if stagen(chain, 'lowpass')
    fc = getf(chain.lowpass, 'cutoff_hz', 2000);
    order = geti(chain.lowpass, 'order', 4);
    if fc > 0 && fc < nyq
        [z, p, k] = butter(order, fc/nyq, 'low');
        [sos, g] = zp2sos(z, p, k);
        Fx = filtfilt(sos, g, Fx); Fy = filtfilt(sos, g, Fy); Fz = filtfilt(sos, g, Fz);
        applied{end+1} = 'lowpass';
    end
end

% ---- notch at spindle harmonics ----
if stagen(chain, 'notch')
    f0 = mean_rpm / 60;
    q  = getf(chain.notch, 'q', 30);
    hs = [];
    if isfield(chain.notch, 'harmonics'); hs = double(chain.notch.harmonics(:))'; end
    for h = hs
        fh = f0 * h;
        if fh > 0 && fh < nyq
            [b, a] = iirnotch(fh/nyq, fh/nyq/q);
            Fx = filtfilt(b, a, Fx); Fy = filtfilt(b, a, Fy); Fz = filtfilt(b, a, Fz);
            applied{end+1} = sprintf('notch%gx', h); %#ok<AGROW>
        end
    end
end
end

function tf = stagen(chain, name)
tf = isfield(chain, name) && isfield(chain.(name), 'on') && logical(chain.(name).on);
end
function v = getf(s, name, default)
v = default; if isfield(s, name) && ~isempty(s.(name)); v = double(s.(name)); end
end
function v = geti(s, name, default)
v = round(getf(s, name, default));
end
