<script setup lang="ts">
// NI-DAQ page: a stylised chassis with each detected C-series module drawn to its real connector
// geometry (BNC / terminal / D-Sub). Click a port to assign it to a channel; "+" on an empty slot
// opens the card catalog. The channel model (roles + physical bindings) drives what the recorder
// captures. Simulated on dev machines, real hardware on the rig.
import { onMounted, ref, computed } from 'vue';
import { nidaqApi, ROLE_COLORS, type Devices, type Channel, type CatalogCard, type Port, type Module } from './nidaqApi';

const devices = ref<Devices | null>(null);
const channels = ref<Channel[]>([]);
const cards = ref<CatalogCard[]>([]);
const loading = ref(false);
const err = ref<string | null>(null);

const pop = ref<{ physical: string; label: string; x: number; y: number } | null>(null);
const catalogFor = ref<number | null>(null); // target slot for add-card

async function load() {
	loading.value = true; err.value = null;
	try {
		const [d, ch, c] = await Promise.all([nidaqApi.devices(), nidaqApi.getChannels(), nidaqApi.catalog()]);
		devices.value = d; channels.value = ch.channels; cards.value = c.cards;
	} catch (e: any) { err.value = e?.message || 'failed to load NI-DAQ config'; }
	finally { loading.value = false; }
}
onMounted(load);

async function save() { try { await nidaqApi.putChannels(channels.value); } catch (e: any) { err.value = e?.message; } }

const byPhysical = computed(() => {
	const m = new Map<string, Channel>();
	for (const c of channels.value) if (c.physical) m.set(c.physical, c);
	return m;
});
function chanFor(physical: string): Channel | undefined { return byPhysical.value.get(physical); }

function openPopover(port: Port, ev: MouseEvent) {
	const r = (ev.currentTarget as HTMLElement).getBoundingClientRect();
	pop.value = { physical: port.physical, label: port.physical, x: Math.min(r.right + 8, window.innerWidth - 250), y: r.top };
}
function assignTo(name: string) {
	const physical = pop.value!.physical;
	channels.value = channels.value.map((c) =>
		c.name === name ? { ...c, physical, source: 'hardware' } : c.physical === physical ? { ...c, physical: null } : c);
	pop.value = null; save();
}
function newAux() {
	const physical = pop.value!.physical;
	const name = window.prompt('Name for the new Aux channel (e.g. Temp, AE):', 'Aux');
	if (!name) return;
	const cleaned = channels.value.map((c) => (c.physical === physical ? { ...c, physical: null } : c));
	cleaned.push({ name, role: 'Aux', physical, sensitivity_pc_per_n: null, gain_n_per_v: null, source: 'hardware', color: ROLE_COLORS.Aux });
	channels.value = cleaned; pop.value = null; save();
}
function unassignPop() {
	const physical = pop.value!.physical;
	channels.value = channels.value.map((c) => (c.physical === physical ? { ...c, physical: null } : c));
	pop.value = null; save();
}
function addVirtual() {
	const name = window.prompt('Name for the virtual channel:', 'Virtual 1');
	if (!name) return;
	channels.value = [...channels.value, { name, role: 'Aux', physical: null, sensitivity_pc_per_n: null, gain_n_per_v: null, source: 'virtual', color: ROLE_COLORS.Virtual }];
	save();
}
function removeChannel(name: string) { channels.value = channels.value.filter((c) => c.name !== name); save(); }
async function autoassign() { try { channels.value = (await nidaqApi.autoassign()).channels; } catch (e: any) { err.value = e?.message; } }

function moduleAt(chassis: { modules: Module[] }, slot: number) { return chassis.modules.find((m) => m.slot === slot); }
async function addCard(product_type: string) {
	if (catalogFor.value == null) return;
	try { devices.value = await nidaqApi.addCard(catalogFor.value, product_type); } catch (e: any) { err.value = e?.message; }
	catalogFor.value = null;
}
async function removeCard(slot: number) { try { devices.value = await nidaqApi.removeCard(slot); } catch (e: any) { err.value = e?.message; } }
</script>

<template>
	<div class="nidaq" @click="pop = null">
		<header class="head">
			<h1>NI-DAQ</h1>
			<span v-if="devices" class="badge" :class="devices.simulated ? 'sim' : 'live'">{{ devices.simulated ? 'SIMULATED' : 'LIVE' }}</span>
			<div class="spacer"></div>
			<button class="btn ghost" @click="autoassign"><span class="material-symbols-rounded">bolt</span> Auto-assign force</button>
			<button class="btn ghost" :disabled="loading" @click="load"><span class="material-symbols-rounded">refresh</span></button>
		</header>
		<p v-if="err" class="err">{{ err }}</p>

		<div class="layout">
			<!-- Chassis diagram(s) -->
			<div class="diagram">
				<div v-for="ch in devices?.chassis || []" :key="ch.name" class="chassis">
					<div class="chassis-top"><b>{{ ch.product_type }}</b><span class="sub">{{ ch.name }} · {{ ch.slots }}-slot</span></div>
					<div class="slots">
						<template v-for="slot in ch.slots" :key="slot">
							<div v-if="moduleAt(ch, slot)" class="mod" @click.stop>
								<div class="mod-head">
									<span class="slotno">SLOT {{ slot }}</span>
									<button class="rm" title="Remove card" @click="removeCard(slot)"><span class="material-symbols-rounded">close</span></button>
								</div>
								<div class="model">{{ moduleAt(ch, slot)!.label }}<span v-if="moduleAt(ch, slot)!.iepe" class="iepe">IEPE</span></div>
								<div class="conn-note">{{ moduleAt(ch, slot)!.note }}</div>
								<!-- ports, connector-specific -->
								<div class="ports" :class="moduleAt(ch, slot)!.connector">
									<button v-for="p in moduleAt(ch, slot)!.ports" :key="p.physical" class="port-row"
										:style="chanFor(p.physical) ? { '--c': chanFor(p.physical)!.color } : {}"
										:class="{ assigned: chanFor(p.physical) }" @click.stop="openPopover(p, $event)">
										<span class="jack" :class="moduleAt(ch, slot)!.connector"></span>
										<span class="pid">{{ p.id }}</span>
										<span v-if="chanFor(p.physical)" class="chip">{{ chanFor(p.physical)!.name }}</span>
										<span v-else class="chip none">—</span>
									</button>
								</div>
							</div>
							<div v-else class="mod empty" @click.stop="catalogFor = slot">
								<span class="slotno">SLOT {{ slot }}</span>
								<div class="plus-wrap"><span class="plus">+</span></div>
							</div>
						</template>
					</div>
				</div>
				<p class="hint">Click a port to assign it to a channel. Click <b>+</b> on an empty slot to add a card.</p>
			</div>

			<!-- Channel model list -->
			<aside class="channels">
				<div class="ch-head"><b>Channels</b><button class="btn tiny" @click="addVirtual">+ Virtual</button></div>
				<div v-for="c in channels" :key="c.name" class="chrow">
					<span class="dot" :style="{ background: c.color }"></span>
					<span class="cname">{{ c.name }}</span>
					<span class="crole">{{ c.role }}</span>
					<span class="cbind" :class="{ unbound: !c.physical }">{{ c.physical || (c.source === 'virtual' ? 'virtual' : 'unbound') }}</span>
					<button class="rm" @click="removeChannel(c.name)"><span class="material-symbols-rounded">close</span></button>
				</div>
				<p v-if="!channels.length" class="hint">No channels — hit Auto-assign force.</p>
			</aside>
		</div>

		<!-- Assign popover -->
		<div v-if="pop" class="popover" :style="{ left: pop.x + 'px', top: pop.y + 'px' }" @click.stop>
			<h4>Assign <code>{{ pop.label }}</code> to</h4>
			<button v-for="c in channels" :key="c.name" class="roleopt" @click="assignTo(c.name)">
				<span class="dot" :style="{ background: c.color }"></span>{{ c.name }} <em>{{ c.role }}</em>
				<span v-if="c.physical === pop.physical" class="cur">current</span>
			</button>
			<div class="pop-sep"></div>
			<button class="roleopt add" @click="newAux"><span class="dot" :style="{ background: ROLE_COLORS.Aux }"></span>+ New aux channel…</button>
			<button class="roleopt add" @click="unassignPop"><span class="material-symbols-rounded">link_off</span> Unassign</button>
		</div>

		<!-- Add-card catalog -->
		<div v-if="catalogFor != null" class="modal" @click.self="catalogFor = null">
			<div class="catalog">
				<div class="cat-head"><b>Add card to Slot {{ catalogFor }}</b><button class="rm" @click="catalogFor = null"><span class="material-symbols-rounded">close</span></button></div>
				<div class="catgrid">
					<button v-for="card in cards" :key="card.product_type" class="cattile" @click="addCard(card.product_type)">
						<span class="ctag">{{ card.connector.toUpperCase() }}<template v-if="card.iepe"> · IEPE</template></span>
						<div class="cname">{{ card.label }}</div>
						<div class="cspec">{{ card.ai ? card.ai + '× AI' : '' }}{{ card.ci ? (card.ai ? ' · ' : '') + card.ci + ' ctr' : '' }}<template v-if="card.note"> · {{ card.note }}</template></div>
					</button>
				</div>
			</div>
		</div>
	</div>
</template>

<style scoped>
.nidaq { min-height: 100vh; background: radial-gradient(1200px 600px at 50% -10%, var(--bg-2), var(--bg)); }
.head { display: flex; align-items: center; gap: 12px; padding: 18px 24px 12px; border-bottom: 1px solid var(--border); }
.head h1 { margin: 0; font-size: 22px; }
.spacer { flex: 1; }
.badge { font-size: 10.5px; font-weight: 700; letter-spacing: .04em; padding: 3px 9px; border-radius: 999px; }
.badge.sim { background: rgba(251,191,36,.16); color: #fbbf24; border: 1px solid rgba(251,191,36,.35); }
.badge.live { background: rgba(74,222,128,.16); color: #4ade80; border: 1px solid rgba(74,222,128,.35); }
.err { color: var(--danger); font-size: 12.5px; padding: 8px 24px 0; }
.layout { display: flex; gap: 20px; padding: 20px 24px; align-items: flex-start; }
.diagram { flex: 1; min-width: 0; }
.chassis { background: linear-gradient(#141b2e,#0e1524); border: 1px solid #2a3550; border-radius: 14px; padding: 14px; margin-bottom: 16px; box-shadow: 0 10px 30px rgba(0,0,0,.3); }
.chassis-top { display: flex; align-items: baseline; gap: 10px; margin-bottom: 12px; }
.chassis-top .sub { color: var(--text-dim); font-size: 12px; }
.slots { display: flex; gap: 8px; align-items: stretch; overflow-x: auto; padding-bottom: 4px; }
/* Portrait modules — real C-series geometry: tall + narrow. */
.mod { flex: 0 0 116px; min-height: 230px; background: #0b1020; border: 1px solid #2a3550; border-radius: 9px; padding: 8px; display: flex; flex-direction: column; }
.mod-head { display: flex; align-items: center; }
.slotno { font-size: 9px; color: #5f6f92; letter-spacing: .05em; }
.mod .rm { margin-left: auto; width: 16px; height: 16px; display: inline-flex; align-items: center; justify-content: center; background: transparent; border: none; color: #5f6f92; cursor: pointer; border-radius: 4px; }
.mod .rm:hover { color: var(--danger); background: rgba(239,68,68,.1); }
.mod .rm .material-symbols-rounded { font-size: 13px; }
.model { font-size: 12px; font-weight: 700; margin: 1px 0 1px; display: flex; align-items: center; gap: 5px; }
.iepe { font-size: 8px; font-weight: 700; padding: 1px 4px; border-radius: 4px; background: rgba(96,165,250,.16); color: #60a5fa; }
.conn-note { font-size: 9px; color: #8ba0c4; margin-bottom: 8px; }
.ports { display: flex; flex-direction: column; gap: 5px; }
.ports.terminal { display: grid; grid-template-columns: 1fr 1fr; gap: 4px; }
.port-row { display: flex; align-items: center; gap: 6px; padding: 4px 5px; border-radius: 7px; background: #0f1730; border: 1px solid #26314e; cursor: pointer; color: inherit; }
.port-row:hover { border-color: #46557d; }
.port-row.assigned { border-color: var(--c); }
.jack { flex: 0 0 auto; }
.jack.bnc { width: 15px; height: 15px; border-radius: 50%; background: radial-gradient(circle at 45% 40%,#33405f,#141b2e 70%); border: 2px solid #52618c; box-shadow: inset 0 0 0 3px #0b1020; }
.jack.terminal { width: 9px; height: 9px; border-radius: 2px; background: #2a3550; border: 1px solid #46557d; }
.jack.dsub { width: 9px; height: 9px; border-radius: 50%; background: #2a3550; border: 1px solid #46557d; }
.port-row.assigned .jack { border-color: var(--c); }
.pid { font-size: 9.5px; color: #7f92b6; }
.port-row.terminal .pid, .ports.terminal .pid { width: 20px; }
.chip { margin-left: auto; font-size: 9.5px; font-weight: 700; padding: 1px 5px; border-radius: 5px; color: var(--c); background: color-mix(in srgb, var(--c) 16%, transparent); }
.chip.none { color: #5f6f92; background: transparent; }
.mod.empty { align-items: stretch; justify-content: flex-start; border-style: dashed; color: #4a5878; cursor: pointer; }
.mod.empty:hover { border-color: #38bdf8; background: rgba(56,189,248,.05); }
.plus-wrap { flex: 1; display: flex; align-items: center; justify-content: center; }
.mod.empty .plus { width: 34px; height: 34px; border-radius: 9px; background: #12305a; border: 1px solid #38bdf8; color: #7dd3fc; font-size: 22px; display: flex; align-items: center; justify-content: center; }
.mod.empty:hover .plus { background: #1a3f6e; }
.hint { font-size: 12px; color: var(--text-dim); margin: 4px 2px 0; }
/* channel list */
.channels { flex: 0 0 300px; background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 12px; }
.ch-head { display: flex; align-items: center; margin-bottom: 8px; }
.ch-head b { flex: 1; }
.chrow { display: flex; align-items: center; gap: 7px; padding: 6px 4px; border-bottom: 1px solid var(--border); font-size: 12px; }
.dot { width: 9px; height: 9px; border-radius: 50%; flex: 0 0 auto; }
.cname { font-weight: 700; width: 46px; }
.crole { color: var(--text-dim); font-size: 10.5px; width: 38px; }
.cbind { flex: 1; font-family: var(--mono); font-size: 10px; color: #9fb2d4; text-align: right; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cbind.unbound { color: #5f6f92; font-style: italic; }
.chrow .rm { width: 16px; height: 16px; display: inline-flex; align-items: center; justify-content: center; background: transparent; border: none; color: #5f6f92; cursor: pointer; }
.chrow .rm:hover { color: var(--danger); }
.chrow .rm .material-symbols-rounded { font-size: 13px; }
/* buttons */
.btn { display: inline-flex; align-items: center; gap: 6px; padding: 8px 12px; font-size: 12.5px; font-weight: 600; border-radius: 8px; cursor: pointer; }
.btn.ghost { color: var(--text); background: var(--surface); border: 1px solid var(--border); }
.btn.ghost:hover:not(:disabled) { background: var(--surface-2); }
.btn:disabled { opacity: .5; cursor: not-allowed; }
.btn .material-symbols-rounded { font-size: 17px; }
.btn.tiny { padding: 4px 8px; font-size: 11px; color: #7dd3fc; background: rgba(56,189,248,.1); border: 1px solid rgba(56,189,248,.3); }
/* popover */
.popover { position: fixed; z-index: 60; width: 234px; background: #0f1730; border: 1px solid #35507d; border-radius: 10px; padding: 8px; box-shadow: 0 14px 40px rgba(0,0,0,.55); max-height: 60vh; overflow: auto; }
.popover h4 { margin: 2px 4px 8px; font-size: 11.5px; font-weight: 600; color: var(--text-dim); }
.popover code { color: #cfe0ff; }
.roleopt { display: flex; align-items: center; gap: 8px; width: 100%; padding: 6px 7px; border-radius: 6px; font-size: 12px; background: transparent; border: none; color: var(--text); cursor: pointer; text-align: left; }
.roleopt:hover { background: #16203c; }
.roleopt em { color: var(--text-dim); font-style: normal; font-size: 10px; }
.roleopt .cur { margin-left: auto; font-size: 9px; color: #4ade80; }
.roleopt.add { color: #9fb2d4; }
.roleopt .material-symbols-rounded { font-size: 15px; }
.pop-sep { height: 1px; background: var(--border); margin: 5px 0; }
/* modal */
.modal { position: fixed; inset: 0; z-index: 70; background: rgba(4,8,18,.6); display: flex; align-items: center; justify-content: center; padding: 24px; }
.catalog { width: min(720px, 96vw); max-height: 82vh; overflow: auto; background: #0d1424; border: 1px solid #33507d; border-radius: 12px; padding: 16px; box-shadow: 0 20px 50px rgba(0,0,0,.6); }
.cat-head { display: flex; align-items: center; margin-bottom: 12px; }
.cat-head b { flex: 1; font-size: 14px; }
.cat-head .rm { background: transparent; border: none; color: var(--text-dim); cursor: pointer; }
.catgrid { display: grid; grid-template-columns: repeat(auto-fill, minmax(158px,1fr)); gap: 10px; }
.cattile { text-align: left; background: #0b1020; border: 1px solid #2a3550; border-radius: 9px; padding: 10px; cursor: pointer; color: var(--text); }
.cattile:hover { border-color: #38bdf8; transform: translateY(-2px); transition: all .12s; }
.ctag { float: right; font-size: 8px; font-weight: 700; padding: 1px 5px; border-radius: 4px; background: #1b2540; color: #9fb2d4; border: 1px solid #2f3c5c; }
.cattile .cname { font-size: 12.5px; font-weight: 700; }
.cattile .cspec { font-size: 9.5px; color: #8ba0c4; margin-top: 2px; }
</style>
