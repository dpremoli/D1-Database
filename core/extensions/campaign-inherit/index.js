// Directus hook: campaign-inherit
//
// Campaigns (machining trials / testing campaigns) group children under a project
// and carry defaults. When a child is created with a campaign set, it should inherit
// the campaign's common fields so the user doesn't re-enter them. When a campaign is
// created under a project, it inherits the project's principal investigator as owner.
//
// Loads before `d1-default-owner` (alphabetical), so a campaign-supplied owner wins;
// d1-default-owner still fills `owner` with the current user when nothing upstream set it.
// All fills are blank-only, so the two hooks compose safely.

const CHILD_COLLECTIONS = new Set(['manufacturing_operations', 'test_sessions']);

const isBlank = (v) => v === undefined || v === null || v === '';

export default ({ filter }) => {
  filter('items.create', async (payload, meta, context) => {
    const collection = meta?.collection;
    const db = context?.database;
    if (!db || !payload) return payload;

    // Child inherits from its campaign.
    if (CHILD_COLLECTIONS.has(collection) && !isBlank(payload.campaign_id)) {
      const campaign = await db('campaigns')
        .where('campaign_id', payload.campaign_id)
        .select('project_id', 'owner', 'default_equipment_id', 'default_material_id')
        .first();
      if (campaign) {
        if (isBlank(payload.project_id) && campaign.project_id) payload.project_id = campaign.project_id;
        if (isBlank(payload.owner) && campaign.owner) payload.owner = campaign.owner;
        if (isBlank(payload.equipment_id) && campaign.default_equipment_id) {
          payload.equipment_id = campaign.default_equipment_id;
        }
        // Only manufacturing_operations carries a material column.
        if (collection === 'manufacturing_operations'
          && isBlank(payload.material_id) && campaign.default_material_id) {
          payload.material_id = campaign.default_material_id;
        }
      }
    }

    // Campaign inherits the project's principal investigator as owner.
    if (collection === 'campaigns' && !isBlank(payload.project_id) && isBlank(payload.owner)) {
      const project = await db('projects')
        .where('project_id', payload.project_id)
        .select('principal_investigator')
        .first();
      if (project?.principal_investigator) payload.owner = project.principal_investigator;
    }

    return payload;
  });
};
