// Every explanatory string the Diagnostics Workbench shows, in one place.
//
// Written against the actual implementations, not the labels: `min_cluster_size` counts
// GRID CELLS (ops.py grid-reduces to `grid_target` cells before clustering), Gi* uses a
// MAD-based sigma rather than the textbook global std, and so on. If a description here
// stops matching scripts/diag/*, the description is the bug.
//
// The workbench has three execution scopes and almost every question an analyst asks is
// really "which of these am I looking at?", so each step carries an explicit scope.

/** Where a step's result comes from, and what it costs to change. */
export type StepScope = 'bake' | 'preview' | 'view';

export const SCOPE_META: Record<StepScope, { label: string; short: string; help: string }> = {
	bake: {
		label: 'Bake only',
		short: 'bake',
		help:
			'Reads the full-rate signal, so it can only run during a Bake on the host — it is '
			+ 'skipped in the live preview. Change it, then Bake to see the effect.',
	},
	preview: {
		label: 'Live preview',
		short: 'live',
		help:
			'Re-runs in about a second over the whole cut at analysis resolution whenever you '
			+ 'edit it. Feeds the Signal chart and the Selection Inspector. Approximate — Bake '
			+ 'for the authoritative numbers.',
	},
	view: {
		label: 'Runs on the framed view',
		short: 'this view',
		help:
			'Also re-runs on just the region you have framed in the Spatial panel, at FULL '
			+ 'resolution (millions of points rather than the analysis grid). That result is '
			+ 'what the Spatial overlay shows. It is a preview: the Bake stays authoritative.',
	},
};

/** Ops whose statistics can be recomputed on the framed viewport. */
export const VIEW_SCOPED_OPS = new Set(['getis_ord', 'hdbscan', 'grow_segmentation', 'gmm_segmentation']);

export function scopeOf(op: string, tier: 'base' | 'derived'): StepScope {
	if (tier === 'base') return 'bake';
	return VIEW_SCOPED_OPS.has(op) ? 'view' : 'preview';
}

export interface StepHelp {
	/** One line: what the step does. */
	summary: string;
	/** Why it is in the pipeline / how to read its output. */
	detail: string;
	/** Per-param prose, keyed by the param key in the recipe. */
	params: Record<string, string>;
}

export const STEP_HELP: Record<string, StepHelp> = {
	frame_transform: {
		summary: 'Rotates the dynamometer XYZ forces into the tool frame (Fc / Ff / Fp).',
		detail:
			'Wear models are defined in the tool frame and the Fc/Ff ratio is a drift-immune '
			+ 'wear indicator, so this sits upstream of everything. Fp is the dyno Z axis, passed '
			+ 'through unrotated. Until a tool_setup supplies a real mount angle, Fc/Ff are XY '
			+ 'under another name.',
		params: {
			channel:
				'Which tool-frame axis drives the rest of the pipeline. Fp (dyno Z) is the default '
				+ 'because Fc/Ff are only a genuine decomposition once Mount ° is real.',
			mount_deg:
				'The static angle at which the dynamometer is mounted relative to the tool. 0 '
				+ 'means Fc/Ff are just Fx/Fy renamed.',
		},
	},
	angular_resample: {
		summary: 'Resamples the signal onto a fixed number of samples per revolution.',
		detail:
			'Everything downstream (TSA especially) needs whole revolutions on a fixed phase '
			+ 'grid. This is why the analysis cloud is ~200k points and not the raw millions — '
			+ 'the raw spiral is still what the Spatial panel renders.',
		params: {
			samples_per_rev:
				'Phase resolution. Higher resolves finer angular features but costs proportionally '
				+ 'more points and cannot invent detail the raw sample rate never captured.',
		},
	},
	tsa: {
		summary: 'Time-synchronous average: the per-revolution repeating signature, removed.',
		detail:
			'Averages every revolution onto one phase grid to get the signature that repeats '
			+ 'turn after turn (runout, insert geometry), then subtracts it. What is left — '
			+ 'tsa_resid — is the part of the force that is NOT explained by the tool going round.',
		params: {},
	},
	radial_detrend: {
		summary: 'Removes the slow radial trend and converts the residual to a robust z-score.',
		detail:
			'Force naturally drifts with cutting radius, so a raw residual is larger at one end '
			+ 'of the part for reasons that are not defects. This bins by radius, removes the '
			+ 'per-bin median, and scales by a MAD-based sigma. The output, resid_z, is "how '
			+ 'many robust standard deviations from normal for this radius" — the input every '
			+ 'spatial statistic below consumes.',
		params: {
			n_bins:
				'How many radial bands the trend is estimated over. More bins track a wigglier '
				+ 'trend but put fewer points in each, making the per-bin median noisier.',
			min_per_bin:
				'A bin with fewer points than this is merged rather than trusted, so a sparse '
				+ 'band at the edge of the cut cannot produce a wild z-score.',
		},
	},
	getis_ord: {
		summary: 'Getis-Ord Gi*: finds spatially clustered highs and lows (hot/cold spots).',
		detail:
			'For each point, compares its neighbourhood mean against the whole cut. A high Gi* '
			+ 'means "this region is jointly high, more than chance" — one big value on its own '
			+ 'does not score; a patch of moderately-high neighbours does. gi_sig is the same '
			+ 'test after false-discovery-rate correction, so it answers "which hotspots survive '
			+ 'multiple testing".',
		params: {
			k:
				'Neighbourhood size — how many nearest points form each local sample. Small k '
				+ 'finds tight spots and is noisy; large k smooths and finds only broad regions.',
			alpha:
				'False-discovery rate for gi_sig. 0.05 means "of the points flagged significant, '
				+ 'accept about 5% being false alarms". Lower is stricter.',
		},
	},
	hdbscan: {
		summary: 'Groups the anomalous points into discrete clusters; the rest becomes noise.',
		detail:
			'Where Gi* gives every point a score, this gives the map discrete objects you can '
			+ 'count and measure. It does NOT take a target number of clusters — it finds however '
			+ 'many are supported by the data, and labels everything else noise (-1). To get '
			+ 'FEWER clusters, RAISE Min cluster size.',
		params: {
			grid_target:
				'The cloud is first reduced to about this many spatial cells, then clustered, then '
				+ 'labels are mapped back to every point. This is what makes clustering millions '
				+ 'of points tractable. Higher = finer spatial detail, slower.',
			min_cluster_size:
				'Minimum size for a group to count as a cluster — measured in GRID CELLS (see '
				+ 'Grid target), not raw points. This is a floor, NOT the number of clusters: '
				+ 'lowering it produces MORE, smaller clusters; raising it produces fewer, and '
				+ 'high enough leaves everything as noise.',
		},
	},
	envelope: {
		summary: 'Demodulates a resonance band to expose impact-rate modulation.',
		detail:
			'Chatter and edge chipping show up as a carrier at the structure’s natural frequency, '
			+ 'amplitude-modulated at the event rate. This band-passes around that frequency and '
			+ 'takes the envelope. It refuses rather than aliasing when the sample rate cannot '
			+ 'support the band — and it needs a measured dynamometer natural frequency, which no '
			+ 'tool_setup record supplies yet.',
		params: {
			fn_hz:
				'The dynamometer / structure natural frequency to demodulate around. Without a '
				+ 'measured value this step refuses to run rather than guess.',
			bandwidth_frac:
				'Band width as a fraction of fₙ. Wider captures more sidebands but admits more '
				+ 'unrelated energy.',
		},
	},
	grow_segmentation: {
		summary: 'Grows painted seed regions outward to segment the whole map.',
		detail:
			'Paint a few example patches per class, bind them below, and label propagation over '
			+ 'a k-NN graph assigns every remaining point to the nearest class in combined '
			+ 'position-and-attribute space. Needs at least two seed classes; below that every '
			+ 'point stays unsegmented (-1).',
		params: {
			k:
				'How many neighbours each point is connected to in the propagation graph. Larger '
				+ 'spreads labels further and smooths boundaries.',
			alpha:
				'How strongly the seeds are clamped. Low keeps painted points fixed to their own '
				+ 'class; high lets the propagation overrule them.',
			attr_weight:
				'How much the attribute (resid_z) counts relative to physical position. 0 segments '
				+ 'on geometry alone; high values follow the residual across space.',
		},
	},
	invert: {
		summary: 'Flips a channel so a "low is bad" reading colours the same way as a "high is bad" one.',
		detail:
			'Not a sign flip and not a deconvolution — a value inversion. Complement (max minus '
			+ 'the value) mirrors the channel around its own peak; reciprocal inverts magnitude '
			+ 'while keeping the original sign, so a small value reads large and vice versa. Useful '
			+ 'on glosh, where a POOR cluster fit reads low, to colour it consistently with resid_z.',
		params: {
			source: 'Which already-computed channel to invert. Must come from an earlier enabled step.',
			mode: 'Complement mirrors around the channel’s own max; reciprocal inverts magnitude only.',
			epsilon: 'Reciprocal mode only — added to the magnitude before dividing, so a value of '
				+ 'exactly zero does not produce an infinite result.',
		},
	},
	griddify: {
		summary: 'Regularises resid_z onto a physical-resolution grid, with an honest confidence map.',
		detail:
			'The point count cannot change (every step after angular_resample must produce the '
			+ 'same number of points), so this is not a denser cloud — it is resid_z resampled '
			+ 'through a grid at Resolution mm, which behaves as a spatial smoothing filter: '
			+ 'coarser than the real point spacing, it averages several real points together. '
			+ 'grid_support is [0, 1] per point — how close it is to its nearest OTHER real '
			+ 'sample relative to Max fill distance. High support means the value nearby is '
			+ 'genuinely measured; low support means it is interpolated across a real gap '
			+ '(the wide angular spacing at large radius is the usual cause).',
		params: {
			resolution_mm: 'Grid pitch in millimetres. Coarser smooths more but blurs finer '
				+ 'features; the real point spacing on this cut is a useful floor.',
			method: 'Linear blends between the nearest real samples; nearest just copies the '
				+ 'closest one — no NaN even at the edge of the data.',
			max_fill_mm: 'Distance in millimetres beyond which grid_support reaches 0 — the '
				+ 'point is now further from any real data than this is willing to call confident.',
		},
	},
	gmm_segmentation: {
		summary: 'Unsupervised segmentation over position and resid_z — no seeds needed.',
		detail:
			'The unsupervised counterpart to Seeded segmentation: a Gaussian mixture over '
			+ '(x, y, resid_z) partitions the whole cut into Components classes with no painted '
			+ 'examples. Unlike HDBSCAN, every point gets a class — there is no noise — and '
			+ 'gmm_prob is a genuine per-point confidence (how sure the model is of that '
			+ 'point’s assignment), which is the reason to reach for this over HDBSCAN.',
		params: {
			n_components: 'How many classes to partition into. Fixed, unlike HDBSCAN which finds '
				+ 'its own count — you are choosing the number of segments up front.',
			covariance_type: 'How each class’s spread is shaped. Full fits an arbitrary ellipse '
				+ 'per class; spherical is the simplest and most stable on noisy data.',
			attr_weight: 'How much resid_z counts relative to physical position. Low partitions on '
				+ 'geometry alone; high follows the residual across space.',
			random_state: 'Seeds the fit so the same recipe gives the same classes every time. '
				+ 'Changing it can relabel which class is which, or find a different local optimum.',
			grid_target: 'The cloud is first reduced to about this many spatial cells before '
				+ 'fitting, the same tractability step HDBSCAN uses. Higher = finer detail, slower.',
		},
	},
};

/** Channel selector help, keyed by ChannelKey. */
export const CHANNEL_HELP: Record<string, string> = {
	residZ:
		'Anomaly z-score: robust standard deviations from the normal force for that cutting '
		+ 'radius. The base map — everything else is derived from it.',
	giStar:
		'Getis-Ord Gi* score. High = a region of jointly-high residual; low = jointly-low. '
		+ 'Reads clustering, not individual outliers.',
	giSig:
		'Which Gi* hotspots survive false-discovery-rate correction. A yes/no version of Gi*.',
	clusterId:
		'HDBSCAN cluster membership. Each colour is one discrete anomaly region; grey is noise '
		+ '(belongs to no cluster).',
	glosh:
		'Outlier score — how poorly a point fits the cluster it was assigned to. High values are '
		+ 'points on the fringe of a group.',
	tsaResid:
		'The residual straight out of TSA, before the radial trend is removed. Useful for '
		+ 'checking whether an apparent defect is really just a radius effect.',
	envBand:
		'Resonance-band envelope amplitude — the impact-rate modulation. Zero everywhere unless '
		+ 'the Envelope step ran with a real natural frequency.',
	segmentId:
		'Seeded segmentation class. Each colour is one of the classes you painted seeds for.',
	inverted:
		'The source channel, inverted (complement or reciprocal). What reads as "bad" is '
		+ 'the same direction as resid_z, whatever the source channel was.',
	gridFill:
		'resid_z regularised onto a physical-resolution grid and read back at each point — a '
		+ 'spatial smoothing of the anomaly map at a chosen millimetre scale.',
	gridSupport:
		'Interpolation confidence, 0–1. High near real, dense data; low where the grid had to '
		+ 'reach further to fill a gap. Colour by this to see how much of grid_fill is invented.',
	gmmId:
		'Gaussian-mixture segment. Unlike HDBSCAN clusters, every point belongs to one — there '
		+ 'is no noise class.',
	gmmProb:
		'Confidence the GMM had in assigning this point to its segment. Low values sit near a '
		+ 'boundary between two segments.',
};

/** Panel-level help, keyed by panel id. */
export const PANEL_HELP: Record<string, string> = {
	spatial:
		'The cut, seen from above, at full resolution. Colour is the selected channel. Pan and '
		+ 'zoom to frame a region — the view-scoped recipe steps recompute on whatever is framed. '
		+ 'Paint tools write mask / label / seed regions in millimetres, so they survive a rebake '
		+ 'at any resolution.',
	recipe:
		'The processing pipeline as an editable program. Steps run top to bottom; each consumes '
		+ 'what earlier ones produce. Toggle a step off to A/B it without losing its tuning. Bake '
		+ 'commits the whole recipe to the host and rewrites the authoritative result.',
	signal:
		'The anomaly z-score (resid_z) along the cut in time order, drawn as a min/max envelope '
		+ 'per time bucket. Tall excursions are moments where the force departed from the normal '
		+ 'trend for that radius. Drag the handles to brush a time window — the Selection '
		+ 'Inspector and the Spatial view both narrow to it.',
	clusters:
		'One row per HDBSCAN cluster, with its size and where it sits radially. Click a row to '
		+ 'isolate that cluster in the Spatial view; click it again to clear.',
	layers:
		'Painted regions, stored as polygons in millimetres. A mask excludes its region from the '
		+ 'statistics (use it for a chuck mark or fixture artefact); seeds mark example regions '
		+ 'for the segmentation step; labels are annotation only.',
};

export const ACTION_HELP = {
	bake:
		'Run the whole recipe on the host over the entire cut at full precision, and save the '
		+ 'result as this cut’s authoritative analysis. Takes a minute or two. This is the only '
		+ 'action that persists anything.',
	runOnView:
		'Recompute just this step over the region currently framed in the Spatial panel, at full '
		+ 'resolution. Takes a second or two, changes nothing stored.',
	build:
		'No analysis exists for this cut yet — run the pipeline on the host to create one.',
	retry: 'The last host run failed. Fix the cause, then run it again.',
	paint:
		'Click to place polygon points on the Spatial view, Enter to close the shape, Esc to '
		+ 'cancel. The region is saved against this cut in millimetres.',
} as const;
