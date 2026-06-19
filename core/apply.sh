#!/usr/bin/env bash
# apply.sh — Bootstrap Directus RBAC and machine users from version control.
#
# Reads core/roles.json and core/permissions.json, creates roles and permissions
# via the Directus REST API, provisions the Rig_1 machine user, and writes a
# schema snapshot to core/schema-snapshot.yaml.
#
# Usage:
#   DIRECTUS_URL=http://localhost:8055 \
#   DIRECTUS_ADMIN_EMAIL=admin@example.com \
#   DIRECTUS_ADMIN_PASSWORD=secret \
#   bash core/apply.sh
#
# All variables may also be set in a .env file at the repo root.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

# ── Load .env if present ──────────────────────────────────────────────────────
if [[ -f "$ROOT/.env" ]]; then
    # shellcheck disable=SC1091
    set -a; source "$ROOT/.env"; set +a
fi

# ── Environment ───────────────────────────────────────────────────────────────
DIRECTUS_URL="${DIRECTUS_URL:-http://localhost:8055}"
: "${DIRECTUS_ADMIN_EMAIL:?DIRECTUS_ADMIN_EMAIL must be set}"
: "${DIRECTUS_ADMIN_PASSWORD:?DIRECTUS_ADMIN_PASSWORD must be set}"

ROLES_FILE="$ROOT/core/roles.json"
PERMISSIONS_FILE="$ROOT/core/permissions.json"
SNAPSHOT_FILE="$ROOT/core/schema-snapshot.yaml"

# ── Pretty-print helpers ──────────────────────────────────────────────────────
info()    { printf '\033[34m[INFO]\033[0m  %s\n' "$*"; }
ok()      { printf '\033[32m[ OK ]\033[0m  %s\n' "$*"; }
warn()    { printf '\033[33m[WARN]\033[0m  %s\n' "$*"; }
die()     { printf '\033[31m[FAIL]\033[0m  %s\n' "$*" >&2; exit 1; }

# ── Dependency checks ─────────────────────────────────────────────────────────
command -v curl  >/dev/null 2>&1 || die "curl is required but not found"
command -v jq    >/dev/null 2>&1 || die "jq is required but not found"

# ── Wait for Directus to be healthy ──────────────────────────────────────────
info "Waiting for Directus at $DIRECTUS_URL (up to 60 s)..."
deadline=$(( $(date +%s) + 60 ))
while true; do
    status=$(curl -sf "$DIRECTUS_URL/server/health" 2>/dev/null \
             | jq -r '.status' 2>/dev/null || true)
    if [[ "$status" == "ok" ]]; then
        ok "Directus is healthy"
        break
    fi
    if [[ $(date +%s) -ge $deadline ]]; then
        die "Directus did not become healthy within 60 s (last status: '${status:-no response}')"
    fi
    sleep 2
done

# ── Authenticate ──────────────────────────────────────────────────────────────
info "Authenticating as $DIRECTUS_ADMIN_EMAIL..."
auth_response=$(curl -sf -X POST "$DIRECTUS_URL/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"$DIRECTUS_ADMIN_EMAIL\",\"password\":\"$DIRECTUS_ADMIN_PASSWORD\"}") \
    || die "Authentication request failed (is Directus running?)"

ACCESS_TOKEN=$(echo "$auth_response" | jq -r '.data.access_token')
[[ -n "$ACCESS_TOKEN" && "$ACCESS_TOKEN" != "null" ]] \
    || die "Could not extract access_token from auth response"
ok "Authenticated — token acquired"

# ── Helper: authenticated curl ────────────────────────────────────────────────
dcurl() {
    # dcurl METHOD ENDPOINT [extra curl args...]
    local method="$1" endpoint="$2"; shift 2
    curl -sf -X "$method" "$DIRECTUS_URL$endpoint" \
        -H "Authorization: Bearer $ACCESS_TOKEN" \
        -H "Content-Type: application/json" \
        "$@"
}

# ── Create roles ──────────────────────────────────────────────────────────────
echo
info "Processing roles from $ROLES_FILE..."

declare -A ROLE_IDS   # name → id

# Fetch existing roles once
existing_roles=$(dcurl GET "/roles?limit=100") \
    || die "Failed to fetch existing roles"

role_count=0
while IFS= read -r role_obj; do
    name=$(echo "$role_obj" | jq -r '.name')
    icon=$(echo "$role_obj" | jq -r '.icon')
    description=$(echo "$role_obj" | jq -r '.description')
    admin_access=$(echo "$role_obj" | jq -r '.admin_access')
    app_access=$(echo "$role_obj" | jq -r '.app_access')

    # Check if role already exists
    existing_id=$(echo "$existing_roles" \
        | jq -r --arg n "$name" '.data[] | select(.name == $n) | .id')

    if [[ -n "$existing_id" && "$existing_id" != "null" ]]; then
        warn "Role '$name' already exists (id=$existing_id) — skipping create"
        ROLE_IDS["$name"]="$existing_id"
    else
        payload=$(jq -n \
            --arg name "$name" \
            --arg icon "$icon" \
            --arg description "$description" \
            --argjson admin_access "$admin_access" \
            --argjson app_access "$app_access" \
            '{name:$name, icon:$icon, description:$description,
              admin_access:$admin_access, app_access:$app_access}')
        response=$(dcurl POST "/roles" -d "$payload") \
            || die "Failed to create role '$name'"
        new_id=$(echo "$response" | jq -r '.data.id')
        [[ -n "$new_id" && "$new_id" != "null" ]] \
            || die "Role '$name' created but no id returned"
        ROLE_IDS["$name"]="$new_id"
        ok "Created role '$name' (id=$new_id)"
        role_count=$((role_count + 1))
    fi
done < <(jq -c '.[]' "$ROLES_FILE")

info "Roles done — $role_count created, $((${#ROLE_IDS[@]} - role_count)) already existed"

# ── Create permissions ────────────────────────────────────────────────────────
echo
info "Processing permissions from $PERMISSIONS_FILE..."

perm_count=0; perm_skip=0
while IFS= read -r perm_obj; do
    # Skip comment-only entries
    role_name=$(echo "$perm_obj" | jq -r '.role // empty')
    [[ -n "$role_name" ]] || { perm_skip=$((perm_skip + 1)); continue; }

    role_id="${ROLE_IDS[$role_name]:-}"
    if [[ -z "$role_id" ]]; then
        warn "No id found for role '$role_name' — skipping permission for $(echo "$perm_obj" | jq -r '.collection').$(echo "$perm_obj" | jq -r '.action')"
        perm_skip=$((perm_skip + 1))
        continue
    fi

    collection=$(echo "$perm_obj" | jq -r '.collection')
    action=$(echo "$perm_obj"     | jq -r '.action')
    fields=$(echo "$perm_obj"     | jq '.fields')
    permissions_filter=$(echo "$perm_obj" | jq '.permissions')
    validation=$(echo "$perm_obj" | jq '.validation')
    presets=$(echo "$perm_obj"    | jq '.presets')

    # Idempotency: skip if a permission for this (role, collection, action)
    # already exists, so re-running apply.sh does not create duplicate rows.
    existing=$(dcurl GET \
        "/permissions?filter[role][_eq]=$role_id&filter[collection][_eq]=$collection&filter[action][_eq]=$action&limit=1" \
        2>/dev/null | jq -r '.data | length' 2>/dev/null || echo 0)
    if [[ "$existing" -gt 0 ]]; then
        perm_skip=$((perm_skip + 1))
        continue
    fi

    payload=$(jq -n \
        --arg role "$role_id" \
        --arg collection "$collection" \
        --arg action "$action" \
        --argjson permissions "$permissions_filter" \
        --argjson validation "$validation" \
        --argjson presets "$presets" \
        --argjson fields "$fields" \
        '{role:$role, collection:$collection, action:$action,
          permissions:$permissions, validation:$validation,
          presets:$presets, fields:$fields}')

    response=$(dcurl POST "/permissions" -d "$payload" 2>&1) \
        || { warn "Failed to create permission $role_name/$collection/$action — $response"; perm_skip=$((perm_skip + 1)); continue; }
    perm_count=$((perm_count + 1))
    ok "Permission $role_name / $collection / $action"
done < <(jq -c '.[]' "$PERMISSIONS_FILE")

info "Permissions done — $perm_count created, $perm_skip skipped/failed"

# ── Create Rig_1 machine user ─────────────────────────────────────────────────
echo
info "Provisioning Rig_1 machine user..."

OPERATOR_ROLE_ID="${ROLE_IDS[Operator]:-}"
[[ -n "$OPERATOR_ROLE_ID" ]] || die "Operator role id not found — cannot create machine user"

# Check if machine user already exists
existing_machine=$(dcurl GET "/users?filter[email][_eq]=rig1@d1-internal.local&limit=1") \
    || die "Failed to query existing users"
existing_machine_id=$(echo "$existing_machine" | jq -r '.data[0].id // empty')

if [[ -n "$existing_machine_id" ]]; then
    warn "Machine user rig1@d1-internal.local already exists (id=$existing_machine_id) — skipping"
else
    # Generate a static token
    if command -v openssl >/dev/null 2>&1; then
        MACHINE_TOKEN=$(openssl rand -hex 32)
    else
        # Fallback: use /dev/urandom
        MACHINE_TOKEN=$(tr -dc 'a-f0-9' < /dev/urandom | head -c 64)
    fi

    machine_payload=$(jq -n \
        --arg email "rig1@d1-internal.local" \
        --arg first_name "Rig_1" \
        --arg last_name "Fast_Sampling_Node" \
        --arg role "$OPERATOR_ROLE_ID" \
        --arg token "$MACHINE_TOKEN" \
        --arg status "active" \
        '{email:$email, first_name:$first_name, last_name:$last_name,
          role:$role, token:$token, status:$status}')

    response=$(dcurl POST "/users" -d "$machine_payload") \
        || die "Failed to create machine user"
    machine_id=$(echo "$response" | jq -r '.data.id')
    ok "Created machine user rig1@d1-internal.local (id=$machine_id)"
    echo
    printf '  \033[33mMACHINE TOKEN (store in vault — printed once):\033[0m\n'
    printf '  %s\n' "$MACHINE_TOKEN"
    echo
fi

# ── Schema snapshot ───────────────────────────────────────────────────────────
echo
info "Generating schema snapshot → $SNAPSHOT_FILE..."
snapshot=$(dcurl GET "/schema/snapshot?export=yaml" 2>&1) \
    || die "Failed to fetch schema snapshot"
echo "$snapshot" > "$SNAPSHOT_FILE"
ok "Schema snapshot written to $SNAPSHOT_FILE"

# ── Summary ───────────────────────────────────────────────────────────────────
echo
echo "╔══════════════════════════════════════════════╗"
echo "║          apply.sh — bootstrap complete        ║"
echo "╠══════════════════════════════════════════════╣"
printf "║  Roles processed   : %-24s ║\n" "${#ROLE_IDS[@]}"
printf "║  Permissions added : %-24s ║\n" "$perm_count"
printf "║  Directus URL      : %-24s ║\n" "$DIRECTUS_URL"
printf "║  Schema snapshot   : %-24s ║\n" "core/schema-snapshot.yaml"
echo "╚══════════════════════════════════════════════╝"
echo
info "Done. Commit core/schema-snapshot.yaml if it changed."
