import { defineInterface } from '@directus/extensions-sdk';
import CampaignOps from './CampaignOps.vue';

// Campaign operations manager whose "add" search is pre-filtered by the campaign's
// type — a Machining Trial only offers machining operations, etc. Assigning/removing
// sets the operation's campaign_id. Shown on the campaign form as an alias field.
export default defineInterface({
	id: 'd1-campaign-ops',
	name: 'Campaign operations (type-filtered)',
	icon: 'build',
	description: 'List + add operations, with the add search pre-filtered by the campaign type.',
	component: CampaignOps,
	types: ['alias'],
	localTypes: ['presentation'],
	group: 'presentation',
	autoKey: true,
	options: [],
});
