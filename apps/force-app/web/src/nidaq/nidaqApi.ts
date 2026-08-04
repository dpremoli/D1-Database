// Frontend helpers for the backend's /nidaq/* endpoints (chassis enumeration + channel model).
// The backend enumerates real hardware on the rig, or a simulated chassis on dev machines.
import { getConfig } from '../config';

function base() { return getConfig().recorderUrl; }

export type Connector = 'bnc' | 'terminal' | 'dsub';
export interface Port { id: string; kind: 'ai' | 'ci'; physical: string; }
export interface Module { name: string; product_type: string; label: string; slot: number; connector: Connector; note: string; iepe: boolean; ports: Port[]; }
export interface Chassis { name: string; product_type: string; slots: number; modules: Module[]; }
export interface Devices { simulated: boolean; chassis: Chassis[]; standalone: Module[]; }
export interface Channel { name: string; role: string; physical: string | null; sensitivity_pc_per_n: number | null; gain_n_per_v: number | null; source: 'hardware' | 'virtual'; color: string; }
export interface CatalogCard { product_type: string; label: string; connector: Connector; ai: number; ci: number; note?: string; vmax?: number; ks?: number; iepe?: boolean; }
export interface ChannelsResp { channels: Channel[]; roles: string[]; colors: Record<string, string>; }

async function j<T>(res: Response): Promise<T> {
	if (!res.ok) throw new Error(`${res.status}: ${(await res.text()).slice(0, 160)}`);
	return res.json() as Promise<T>;
}
const JSON_H = { 'Content-Type': 'application/json' };

export const nidaqApi = {
	devices: () => fetch(`${base()}/nidaq/devices`).then(j<Devices>),
	catalog: () => fetch(`${base()}/nidaq/catalog`).then(j<{ cards: CatalogCard[] }>),
	addCard: (slot: number, product_type: string) =>
		fetch(`${base()}/nidaq/sim/card`, { method: 'POST', headers: JSON_H, body: JSON.stringify({ slot, product_type }) }).then(j<Devices>),
	removeCard: (slot: number) =>
		fetch(`${base()}/nidaq/sim/card?slot=${slot}`, { method: 'DELETE' }).then(j<Devices>),
	getChannels: () => fetch(`${base()}/nidaq/channels`).then(j<ChannelsResp>),
	putChannels: (channels: Channel[]) =>
		fetch(`${base()}/nidaq/channels`, { method: 'PUT', headers: JSON_H, body: JSON.stringify({ channels }) }).then(j<{ channels: Channel[] }>),
	autoassign: () => fetch(`${base()}/nidaq/channels/autoassign`, { method: 'POST' }).then(j<{ channels: Channel[] }>),
};

export const ROLE_COLORS: Record<string, string> = { Fx: '#f87171', Fy: '#4ade80', Fz: '#60a5fa', Tacho: '#c084fc', Aux: '#fbbf24', Virtual: '#38bdf8' };
