// The 12-entry categorical palette shared by DiagScatter (GPU) and ClusterTable (CSS chips),
// so a cluster's colour matches between the point cloud and its table row. Tableau-10 plus two.
export const CLUSTER_PALETTE: [number, number, number][] = [
	[0.30, 0.69, 0.29], [0.22, 0.49, 0.72], [0.89, 0.47, 0.10], [0.60, 0.31, 0.64],
	[0.90, 0.62, 0.00], [0.65, 0.34, 0.16], [0.97, 0.51, 0.75], [0.50, 0.50, 0.50],
	[0.74, 0.74, 0.13], [0.09, 0.75, 0.81], [0.84, 0.15, 0.16], [0.17, 0.63, 0.17],
];

/** CSS rgb() for a cluster id. id < 0 (HDBSCAN noise) is a neutral grey. */
export function clusterColorCss(id: number): string {
	if (id < 0) return 'rgb(120, 120, 120)';
	const [r, g, b] = CLUSTER_PALETTE[Math.floor(id) % CLUSTER_PALETTE.length];
	return `rgb(${Math.round(r * 255)}, ${Math.round(g * 255)}, ${Math.round(b * 255)})`;
}
