// NI-DAQ page state that outlives the page (#109, same pattern as labamp/labampStore.ts): the
// last-known devices/channels/catalog show at once on the next visit and refresh in the background.
import { createSwr } from '../ui/swr';
import { nidaqApi, type CatalogCard, type Channel, type Devices } from './nidaqApi';

export interface NidaqSnapshot {
	devices: Devices;
	channels: Channel[];
	cards: CatalogCard[];
}

export const nidaqState = createSwr<NidaqSnapshot>(async () => {
	const [devices, ch, c] = await Promise.all([nidaqApi.devices(), nidaqApi.getChannels(), nidaqApi.catalog()]);
	return { devices, channels: ch.channels, cards: c.cards };
});
