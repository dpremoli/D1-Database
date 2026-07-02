<template>
	<div class="geometry-preview">
		<div v-if="!geometry || geometry === 'other'" class="no-data">
			<span class="notice">Select a geometry to see a shape preview</span>
		</div>

		<!-- Cylinder (tall) -->
		<svg v-else-if="geometry === 'cylindrical'" viewBox="0 0 200 220" xmlns="http://www.w3.org/2000/svg">
			<defs>
				<marker id="ah" markerWidth="6" markerHeight="6" refX="3" refY="3" orient="auto">
					<path d="M0,0 L6,3 L0,6 Z" fill="#666"/>
				</marker>
				<marker id="aht" markerWidth="6" markerHeight="6" refX="3" refY="3" orient="auto-start-reverse">
					<path d="M0,0 L6,3 L0,6 Z" fill="#666"/>
				</marker>
			</defs>
			<!-- Body -->
			<rect x="55" y="30" width="90" height="150" fill="#E3F2FD" stroke="#1565C0" stroke-width="1.5"/>
			<!-- Top ellipse -->
			<ellipse cx="100" cy="30" rx="45" ry="12" fill="#BBDEFB" stroke="#1565C0" stroke-width="1.5"/>
			<!-- Bottom ellipse (visible arc) -->
			<path d="M 55 180 A 45 12 0 0 0 145 180" fill="none" stroke="#1565C0" stroke-width="1.5" stroke-dasharray="4,3"/>
			<path d="M 55 180 A 45 12 0 0 1 145 180" fill="#D6EAF8" stroke="#1565C0" stroke-width="1.5"/>
			<!-- Centreline -->
			<line x1="100" y1="18" x2="100" y2="195" stroke="#999" stroke-width="0.8" stroke-dasharray="4,3"/>
			<!-- Diameter arrow -->
			<line x1="55" y1="205" x2="145" y2="205" stroke="#666" stroke-width="1" marker-end="url(#ah)" marker-start="url(#aht)"/>
			<text x="100" y="216" text-anchor="middle" font-size="10" fill="#333">{{ dLabel('Ø', diameter_mm) }}</text>
			<!-- Length arrow -->
			<line x1="152" y1="30" x2="152" y2="180" stroke="#666" stroke-width="1" marker-end="url(#ah)" marker-start="url(#aht)"/>
			<text x="168" y="110" text-anchor="middle" font-size="10" fill="#333" transform="rotate(90,168,110)">{{ dLabel('L', length_mm) }}</text>
			<!-- Mass badge -->
			<text v-if="massLabel" x="100" y="115" text-anchor="middle" font-size="9" fill="#555">{{ massLabel }}</text>
		</svg>

		<!-- Disc (flat cylinder) -->
		<svg v-else-if="geometry === 'disc'" viewBox="0 0 200 150" xmlns="http://www.w3.org/2000/svg">
			<defs>
				<marker id="ah2" markerWidth="6" markerHeight="6" refX="3" refY="3" orient="auto">
					<path d="M0,0 L6,3 L0,6 Z" fill="#666"/>
				</marker>
				<marker id="aht2" markerWidth="6" markerHeight="6" refX="3" refY="3" orient="auto-start-reverse">
					<path d="M0,0 L6,3 L0,6 Z" fill="#666"/>
				</marker>
			</defs>
			<!-- Body -->
			<rect x="35" y="55" width="130" height="30" fill="#E3F2FD" stroke="#1565C0" stroke-width="1.5"/>
			<!-- Top ellipse -->
			<ellipse cx="100" cy="55" rx="65" ry="14" fill="#BBDEFB" stroke="#1565C0" stroke-width="1.5"/>
			<!-- Bottom ellipse arc (visible) -->
			<path d="M 35 85 A 65 14 0 0 1 165 85" fill="#D6EAF8" stroke="#1565C0" stroke-width="1.5"/>
			<path d="M 35 85 A 65 14 0 0 0 165 85" fill="none" stroke="#1565C0" stroke-width="1" stroke-dasharray="4,3"/>
			<!-- Diameter arrow -->
			<line x1="35" y1="115" x2="165" y2="115" stroke="#666" stroke-width="1" marker-end="url(#ah2)" marker-start="url(#aht2)"/>
			<text x="100" y="126" text-anchor="middle" font-size="10" fill="#333">{{ dLabel('Ø', diameter_mm) }}</text>
			<!-- Thickness arrow -->
			<line x1="172" y1="55" x2="172" y2="85" stroke="#666" stroke-width="1" marker-end="url(#ah2)" marker-start="url(#aht2)"/>
			<text x="188" y="73" text-anchor="middle" font-size="9" fill="#333" transform="rotate(90,188,73)">{{ dLabel('t', thickness_mm) }}</text>
			<!-- Mass -->
			<text v-if="massLabel" x="100" y="73" text-anchor="middle" font-size="9" fill="#555">{{ massLabel }}</text>
		</svg>

		<!-- Rectangular (cuboid) -->
		<svg v-else-if="geometry === 'rectangular'" viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg">
			<defs>
				<marker id="ah3" markerWidth="6" markerHeight="6" refX="3" refY="3" orient="auto">
					<path d="M0,0 L6,3 L0,6 Z" fill="#666"/>
				</marker>
				<marker id="aht3" markerWidth="6" markerHeight="6" refX="3" refY="3" orient="auto-start-reverse">
					<path d="M0,0 L6,3 L0,6 Z" fill="#666"/>
				</marker>
			</defs>
			<!-- Front face -->
			<rect x="30" y="50" width="100" height="80" fill="#E8F5E9" stroke="#2E7D32" stroke-width="1.5"/>
			<!-- Top face (parallelogram) -->
			<polygon points="30,50 130,50 160,20 60,20" fill="#C8E6C9" stroke="#2E7D32" stroke-width="1.5"/>
			<!-- Right face (parallelogram) -->
			<polygon points="130,50 160,20 160,100 130,130" fill="#A5D6A7" stroke="#2E7D32" stroke-width="1.5"/>
			<!-- Width arrow (bottom) -->
			<line x1="30" y1="145" x2="130" y2="145" stroke="#666" stroke-width="1" marker-end="url(#ah3)" marker-start="url(#aht3)"/>
			<text x="80" y="156" text-anchor="middle" font-size="10" fill="#333">{{ dLabel('W', width_mm) }}</text>
			<!-- Height arrow (left) -->
			<line x1="18" y1="50" x2="18" y2="130" stroke="#666" stroke-width="1" marker-end="url(#ah3)" marker-start="url(#aht3)"/>
			<text x="8" y="93" text-anchor="middle" font-size="9" fill="#333" transform="rotate(-90,8,93)">{{ dLabel('H', thickness_mm) }}</text>
			<!-- Depth arrow (top-right) -->
			<line x1="137" y1="13" x2="167" y2="13" stroke="#666" stroke-width="1" marker-end="url(#ah3)" marker-start="url(#aht3)"/>
			<text x="152" y="10" text-anchor="middle" font-size="9" fill="#333">{{ dLabel('L', length_mm) }}</text>
			<!-- Mass -->
			<text v-if="massLabel" x="80" y="95" text-anchor="middle" font-size="9" fill="#555">{{ massLabel }}</text>
		</svg>

		<!-- Powder -->
		<svg v-else-if="geometry === 'powder'" viewBox="0 0 200 160" xmlns="http://www.w3.org/2000/svg">
			<!-- Jar outline -->
			<rect x="55" y="55" width="90" height="80" rx="4" fill="#FFF8E1" stroke="#F57F17" stroke-width="1.5"/>
			<!-- Lid -->
			<rect x="48" y="44" width="104" height="18" rx="3" fill="#FFCC80" stroke="#F57F17" stroke-width="1.5"/>
			<!-- Powder fill -->
			<ellipse cx="100" cy="135" rx="45" ry="8" fill="#FFE082" stroke="#F57F17" stroke-width="1"/>
			<!-- Powder particles -->
			<circle cx="72" cy="100" r="4" fill="#FFD54F"/>
			<circle cx="85" cy="88" r="3" fill="#FFCA28"/>
			<circle cx="100" cy="95" r="5" fill="#FFD54F"/>
			<circle cx="115" cy="85" r="3" fill="#FFCA28"/>
			<circle cx="128" cy="100" r="4" fill="#FFD54F"/>
			<circle cx="95" cy="110" r="3" fill="#FFCA28"/>
			<circle cx="110" cy="112" r="3.5" fill="#FFD54F"/>
			<text x="100" y="170" text-anchor="middle" font-size="10" fill="#E65100">Powder / Compact</text>
			<text v-if="massLabel" x="100" y="120" text-anchor="middle" font-size="9" fill="#BF360C">{{ massLabel }}</text>
		</svg>

		<!-- Dimension summary strip -->
		<div class="dims">
			<span v-if="geometry === 'cylindrical' || geometry === 'disc'">
				<b>Ø</b> {{ fmtDim(diameter_mm) }}
			</span>
			<span v-if="geometry === 'cylindrical'"><b>L</b> {{ fmtDim(length_mm) }}</span>
			<span v-if="geometry === 'disc'"><b>t</b> {{ fmtDim(thickness_mm) }}</span>
			<span v-if="geometry === 'rectangular'"><b>W</b> {{ fmtDim(width_mm) }} × <b>L</b> {{ fmtDim(length_mm) }} × <b>H</b> {{ fmtDim(thickness_mm) }}</span>
			<span v-if="massLabel"><b>m</b> {{ massLabel }}</span>
		</div>
	</div>
</template>

<script setup lang="ts">
import { inject, computed, ref, watch, type Ref } from 'vue';
import { useApi } from '@directus/extensions-sdk';

// Directus 11 injects the live form values as a Vue Ref — read `.value`.
const values = inject<Ref<Record<string, any>>>('values', ref({}));
const v = computed(() => values.value ?? {});
const api = useApi();

const num = (x: any): number | null => {
	const n = typeof x === 'string' ? parseFloat(x) : x;
	return typeof n === 'number' && !Number.isNaN(n) ? n : null;
};

const geometry     = computed(() => v.value.form ?? null);
const diameter_mm  = computed(() => num(v.value.diameter_mm));
const length_mm    = computed(() => num(v.value.length_mm));
const thickness_mm = computed(() => num(v.value.thickness_mm));
const width_mm     = computed(() => num(v.value.width_mm));
const enteredMass  = computed(() => num(v.value.mass_grams));

// Material density (g/cm³) looked up from the selected material.
const density = ref<number | null>(null);
watch(
	() => v.value.material_id,
	async (id) => {
		if (!id) { density.value = null; return; }
		try {
			const res = await api.get(`/items/materials/${id}`, {
				params: { fields: ['density_g_per_cm3'] },
			});
			density.value = num(res?.data?.data?.density_g_per_cm3);
		} catch {
			density.value = null;
		}
	},
	{ immediate: true },
);

// Volume (mm³) from geometry + dimensions.
const volumeMm3 = computed<number | null>(() => {
	const d = diameter_mm.value, L = length_mm.value, t = thickness_mm.value, w = width_mm.value;
	switch (geometry.value) {
		case 'cylindrical': return d && L ? Math.PI * (d / 2) ** 2 * L : null;
		case 'disc':        return d && t ? Math.PI * (d / 2) ** 2 * t : null;
		case 'rectangular': return w && L && t ? w * L * t : null;
		default:            return null;
	}
});

// Estimated mass (g) = volume(cm³) × density(g/cm³).
const estMass = computed<number | null>(() => {
	if (volumeMm3.value == null || density.value == null) return null;
	return (volumeMm3.value / 1000) * density.value;
});

// Show entered mass if present, else the estimate.
const isEstimate = computed(() => enteredMass.value == null && estMass.value != null);
const massValue = computed<number | null>(() =>
	enteredMass.value != null ? enteredMass.value : estMass.value,
);
const massLabel = computed<string | null>(() => {
	if (massValue.value == null) return null;
	const g = massValue.value >= 100 ? massValue.value.toFixed(0) : massValue.value.toFixed(2);
	return isEstimate.value ? `≈ ${g} g (est.)` : `${g} g`;
});

function fmtDim(x: number | null): string {
	return x == null ? '—' : `${x} mm`;
}
function dLabel(label: string, x: number | null): string {
	return x != null ? `${label}: ${x} mm` : label;
}
</script>

<style scoped>
.geometry-preview {
	display: flex;
	flex-direction: column;
	align-items: center;
	gap: 8px;
	padding: 12px 0;
}

.geometry-preview svg {
	max-width: 200px;
	height: auto;
	filter: drop-shadow(0 1px 3px rgba(0,0,0,0.15));
}

.no-data .notice {
	color: var(--foreground-subdued, #999);
	font-style: italic;
	font-size: 13px;
}

.dims {
	display: flex;
	flex-wrap: wrap;
	gap: 12px;
	font-size: 12px;
	color: var(--foreground-normal, #333);
	justify-content: center;
}

.dims span {
	background: var(--background-subdued, #f5f5f5);
	padding: 2px 8px;
	border-radius: 4px;
}
</style>
