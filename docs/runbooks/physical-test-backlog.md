# Physical test backlog

Checks that cannot be done in a cloud session or in CI. Each one needs a running Directus (the
local Docker stack with real data), the force-capture rig (NI-DAQ chassis, Lab Amp, packaged
Windows app), or `d1-server`. Code for every item below is merged and unit-tested; what is missing
is the confirmation on the real thing.

**This is a running list.** Any change whose PR says "not tested on real systems" adds its checks
here in the same PR (see `CLAUDE.md`). When you run a check:

1. Tick it (`[x]`), and add the date, who ran it and the result after the item, e.g.
   `— 2026-10-12, DP: OK` or `— 2026-10-12, DP: FAIL, see #131`.
2. If it fails, open an issue and link it; leave the box unticked until the fix is checked too.
3. Move fully ticked sections to **Done** at the bottom once a month or so, so the open list stays
   short.

Item ids are the UX review's (`docs/reviews/2026-10-05-ux-utility-review.md`) or the GitHub issue
number. "Since" is the PR that shipped the code.

## A. Live Directus (local stack with real data)

Start with `make up`, apply migrations (`make migrate`) and the configure scripts
(`scripts/configure_all.sh`), restart Directus so new extensions load, then sign in as each role
named in the step.

### Permissions and migrations
- [ ] **Migrations 133–135 on a real Directus database** (not the CI stub tables). `dbmate up`
  applies cleanly; `dbmate down` three times then `up` again. Since #123/#125.
- [ ] **X2 — a Lab Member can save a cut.** Sign in to the Force App as a Lab Member, record a sim
  cut, save with upload. Expect: the operation row, both files and the `machining_force_analysis`
  row are created; no 403. Then open that cut's live cache in Force Analysis. Since #123.
- [ ] **Configure script keeps migration grants.** Run `scripts/configure_users_and_policies.sql`
  twice; repeat the Lab Member save above. Since #123.
- [ ] **Lab Member file reads.** Confirm a Lab Member can open colleagues' live caches but note what
  else `/assets/<id>` exposes (equipment images, admin uploads). Feeds the Phase 9 export-control
  decision (ADR-0005). Since #123.

- [ ] **P10 — Diagnostics picker as a Lab Member.** Sign in to the Force App as a Lab Member and open
  Diagnostics: the list loads; campaign grouping is shown if the role can read `campaigns`, and
  otherwise *Group by* offers Sample only (no empty list). Note which it was; if Lab Member cannot
  read campaigns and the lab wants them, add the read grant by migration. Since: this batch (PR TBD).

### Sample numbers, dashboards, saved filters
- [ ] **D9 — next sample number.** `GET /d1-next-number/sample` returns a number when signed in,
  401 signed out, 403 for a user without app access. The Register-sample page and the sample-code
  interface show the same preview; a Lab Member whose role hides some samples still gets the true
  next number. Since #123.
- [ ] **D7 — dashboard links.** Every "Open in Directus" link on the Sample, Machining and FAST
  dashboards opens the right record. Since #123.
- [ ] **D12 — saved filters.** In Operations, Tests and Samples, the seven bookmarks appear for
  every role. "My operations"/"My samples" show only records whose owner person is linked to the
  signed-in user. "FAST runs, last 7 days", "Missing outcome", "Failed", "Needs analysis" and "No
  location" match a hand count. Re-run `scripts/configure_directus.sql`: they are still there,
  once each. Since #125.

### Ask-DB
- [ ] **D1/D2 — chips and messages.** The five example chips run and answer. A query returning more
  than the row limit shows "Showing the first N rows". Stop the `llm-text-to-sql` container: the
  chat says the model is unreachable. Set a wrong `WORKER_WEBHOOK_SECRET` in Directus: the chat
  says the server is misconfigured (not "sign in again"). Since #123.
- [ ] **D3 — export and history.** Download CSV opens cleanly in Excel (BOM, no formula runs from a
  cell starting with `=`). Copy SQL works on the plain-http host. Two users signing in one after
  the other in the same browser see only their own Recent and Saved questions. Since #124.

### Sample labels and QR
- [ ] **D4 — label sheets.** From a sample form, "Print label" and "Print several labels"; from Home,
  the "Print labels" tile. Print the A4 sheet on L7160 (63.5 × 38.1 mm, 21-up) and one 50 × 25 mm
  label: text and QR sit inside each label, the `start` offset skips used labels. Since #124.
- [ ] **D4 — scan to open.** Scan a printed QR with a phone on the lab network: it asks to sign in,
  then opens that sample's record. Nothing is visible without signing in. Since #124.
- [ ] **D4 — permissions and dates.** A role that cannot read a sample gets "not found" for it in a
  label request. With `D1_TIMEZONE=Europe/London` set, a sample created just after midnight BST
  prints the right date. The picker shows "(200 of N)" when there are more than 200. Since #124.

### Plot dashboard inside Directus
- [ ] **P3 — links in the Directus module.** "Copy link" in the Directus-hosted Plot opens the same
  view in another browser. Check the browser's network tab: changing the view does not flood
  `PATCH /users/me/track/page`. Since #124.
- [ ] **P2 — PNG export in Directus.** "Save chart as PNG" and "as SVG" download a correct image
  (Directus's CSP allows the `blob:` image used for the PNG). Since #125.

### Sample timeline and campaign overview
- [ ] **D5 — timeline on a real sample with genealogy.** Restart Directus so `d1-trace` and the
  rebuilt Lab Dashboard load. Lab Dashboard > Samples > pick a sample that has a parent, a child, a
  raw stock lot, operations and tests > **Timeline** tab. Expect: stock lot, ancestors (oldest
  first), the sample, operations and tests in date order, then descendants, matching
  `SELECT * FROM f_sample_timeline('<id>')` and the `f_trace_*` functions run by hand. Every entry
  opens its record. `GET /d1-trace/sample/<id>` is 401 signed out, 403 for a user without app
  access, 400 for a bad id. Since: this batch (PR TBD).
- [ ] **D5 — hidden items for a restricted role.** Sign in as a role whose item filter hides some
  of that sample's relatives, operations or tests. Expect: the Timeline shows only what the role can
  open, with "N items are not visible to you" lines where something was dropped; no code, id or
  operator of a hidden record appears in the JSON of `/d1-trace/sample/<id>`; a sample the role
  cannot read gives "not visible to you" (404). Field level: give the role a field rule that hides
  `form` (samples), `pass_code` or `operation_date` (operations), `status` (tests), `supplier_name`
  (lots), `fraction` or `mass_used_grams` (genealogy, stock provenance): the JSON has `null` for
  that field and the Timeline shows the record without it. A role with no access to
  `sample_genealogy` still sees the relatives, just without relationship type or fraction. A raw
  stock lot reached through a hidden ancestor reads "via a sample you cannot see". Since: this batch
  (PR TBD).
- [ ] **D5 — diamond genealogy and a huge genealogy.** On a sample whose ancestors merge (two
  parents that share a grandparent) each sample appears once in the Timeline and the counts match
  `SELECT count(DISTINCT sample_id) FROM f_trace_ancestors('<id>')` minus the sample itself. On a
  real database, time `GET /d1-trace/sample/<id>` for the sample with the largest genealogy: it
  answers within the 8 s limit, or with "this sample's genealogy is too large to trace" (503)
  shown in the tab; either way Postgres is not left running the query (`pg_stat_activity`). Since
  migration 136 the functions walk samples, not paths, so the 503 should no longer happen (the 8 s
  deadline stays as a safety net; see the next item). With more than 500 ancestors, descendants or events the tab says only the nearest
  500 relatives / newest 500 operations and tests are shown. Since: this batch (PR TBD).
- [ ] **Genealogy functions on the deepest real genealogy (migration 136, f_trace_* visit each
  sample once).** On the real database find the sample with the largest genealogy (most rows in
  `f_trace_ancestors` / `f_trace_descendants` by walking `sample_genealogy`, or the deepest chain).
  Run `SELECT count(*), max(depth) FROM f_trace_ancestors('<id>')` and the descendants one, and
  `GET /d1-trace/sample/<id>` (and the Timeline tab). Expect: each answers in well under a second
  with `count(*) = count(DISTINCT sample_id)`. Compare against the old definition: run the
  `-- migrate:down` SQL of `20261006000136` inside a transaction you roll back (only if the
  genealogy is small enough for path enumeration, otherwise skip the comparison) and check that
  `SELECT DISTINCT sample_id` and `min(depth)` per sample are the same. In the Timeline, hidden-item
  counts for a restricted role are unchanged from before the migration for a sample with a diamond
  genealogy. Since: this batch (PR TBD).
- [ ] **D11 — campaign overview counts.** Open a machining trial and a testing campaign that have
  real data. Expect: sample, operation and test-session counts equal a hand count in the
  collection lists; "Force analysed n / m" equals the machining operations whose
  `machining_force_analysis` rows are all `done` (operations whose files are all `skipped` are not
  counted, and "Diagnostics built" needs every file built); the per-operation force-analysis and diagnostics
  badges match the Force Analysis page, and an `error` badge shows the message on hover. As a role
  that cannot read `machining_force_analysis`, the force columns show "—" and a note, not an error.
  "Tests complete n / m" counts test sessions whose status is `processed` or `analysed` (compare
  with a status filter on the Test Sessions list), and the status chips use the real vocabulary
  (`registered`, `pending processing`, `processing`, `processed`, `analysing`, `analysed`,
  `failed`). Since: this batch (PR TBD).
- [ ] **D11 — pickers.** In a campaign, add a sample by code, then a test session that is in no
  campaign: each appears in the overview, the counts rise, and the test session shows the campaign
  in its own form. Remove both again. A sample that only appears through an operation is marked
  "not in list" and its + button adds it. Also add and remove an operation and check the overview
  reloads. Race checks, with the campaign open in two browser tabs: add the same test session in
  both, the second gives "already in another campaign" (not an error from Directus) and the
  session stays in the first campaign; add the same sample in both, the second just reloads with no
  error. The batch `PATCH /items/test_sessions` answer lists the changed row for a role that may
  read test sessions, so a normal add never shows the "already in another campaign" note. Since:
  this batch (PR TBD).

## B. Force rig (NI-DAQ, Lab Amp, packaged Windows app)

Install the current release from the update feed on the acquisition PC. Use a real sample and
tool; a test cut on scrap stock is fine.

### Recording
- [ ] **R4 — pre-flight chips.** With the Lab Amp in MEASURE: Amp chip OK. In RESET: OK (Start
  cycles it). Unplugged/unreachable: warning. Channels chip checks the saved NI-DAQ model and goes
  to "fail" when a configured channel is missing from the chassis. Disk chip's "~N min" roughly
  matches free space ÷ data rate. Since #124.
- [ ] **R5 — live clipping.** Drive one channel to its rail (lower the amp range, or a known
  overload) at a Lab Amp full scale of 10 V, then 5 V. Expect the red banner naming that channel,
  the tile and badge, and after the cut `channels_ranging.clipped` true for the same channel only.
  Since #124.
- [ ] **R6 — alarms on hardware.** Early warning at 80 % of the force limit (amber, no tone). With
  "Stop the recording when the force alarm trips" on, a trip stops the cut, the alarm stays on top
  of the save dialog and A acknowledges it. With a tone volume set, Windows volume is not changed.
  Since #125.
- [ ] **R10 — shortcuts in the packaged app.** Ctrl+Enter starts (through the pre-flight and alarm
  test), Ctrl+. stops, A acknowledges, Ctrl+N starts a new cut, Enter saves. Press Alt once, then
  A during an alarm: A must still acknowledge (Alt opens menu mode on Windows). Since #125.
- [ ] **R1/R3 — remembered setup.** Quit and relaunch: Sample, Machine, Operator, op type and cut
  parameters are back. Open a cut in Replay, then switch to NI-DAQ: the form shows your setup, not
  the archived cut's sample, edge or sequence. New steps the sequence. Since #123.
- [ ] **Leaving the page mid-cut.** Start a cut, go to Plot, come back after it ends: the save dialog
  offers to save it. Since #123 (doc fix).

### Captures list (thousands of captures on the real drive)
- [ ] **R9 — browse speed on the real capture drive.** With the capture drive holding about 1,000
  or more captures (a network drive if that is what the lab uses; copy old captures in if needed),
  open Settings > Local Captures. Expect the first 200 rows within a few seconds, "Showing 200 of
  N" with the true N, and Load more adding the next page. Press Refresh again: a warm scan should
  be clearly faster than the first. Note both times and the drive type here. Since: this batch (PR
  TBD).
- [ ] **R9 — search, sort and filters at scale.** Search a sample name, a date (`2026-10-02`) and an
  id fragment: results match a hand check in File Explorer. Sort by Largest first: the top rows are
  the biggest folders. The Not uploaded and Uploaded chips keep loading pages and the footer's
  "checked" count makes sense. Needs a real Directus so the uploaded state is real. Since: this
  batch (PR TBD).
- [ ] **R9 — bulk delete frees the space.** Select a handful of uploaded captures and Delete
  selected: the confirm's space total matches the drive's free space gained (Explorer or the
  "Free on drive" figure after Refresh), the folders are gone, and the remote backup copy is marked
  deleted rather than removed. Include one not-uploaded capture: the only-copy warning appears.
  Cancel mid-run: the rest are untouched. Since: this batch (PR TBD).
- [ ] **R9 — cleanup never touches unsynced captures.** With real uploaded and not-uploaded
  captures older than N days, Free up space > Preview lists only captures that have a real
  `manufacturing_operations` row AND a `machining_force_analysis` row with `live_cache_file` (and
  `directus_files_id` when a `.mat` exists); cross-check three in Directus. Make one orphan: in
  Directus delete the analysis row of an old uploaded capture (or stop an upload after the run row
  is created); it must show "partial upload", keep its Upload button, be absent from the preview,
  and get the only-copy warning in a bulk delete. Not-uploaded, incomplete and
  queued ones are absent at any N. Run it and confirm those are still on disk. Repeat with Directus
  stopped: the preview must refuse. Since: this batch (PR TBD).
- [ ] **R9 — upload-all progress and cancel against the real Directus.** With three or more
  not-uploaded captures, Upload N unsynced: the bar shows "Uploading n of m" and the capture name,
  Cancel stops after the current one and says how many were not attempted, and each uploaded
  capture has exactly one operation row (no duplicates after cancelling and running again). While
  it runs, Delete selected, Free up space and the row Upload buttons are disabled; click a row's
  Upload just before Upload N unsynced: that capture is still uploaded once. Open a row's Delete
  confirm, leave it open until Upload all reaches that row, then confirm: nothing is deleted and
  the row says it was busy. Since: this batch (PR TBD).
- [ ] **R9 — a partial upload is completed, not skipped.** In Directus, clear `directus_files_id`
  on the `machining_force_analysis` row of a capture that has a `capture.mat` (it then shows
  "partial upload"). Press its Upload: expect no second operation row, no second analysis row, the
  `.mat` uploaded once and its link filled in on the same row (the live cache file link and file
  are untouched), and only then the row shows "Uploaded". Repeat clearing `live_cache_file`
  instead. Then Upload on a complete one is not offered. Also stop Directus right after an upload
  returns: the row must not show as uploaded without the check. Since: this batch (PR TBD).

### Desktop shell
- [ ] **R11 — Restart recorder.** Kill the backend (Task Manager): the Doctor's "Restart recorder"
  brings it back and the doctor goes green. While recording: it refuses. With the backend hung
  (not answering, still running): it asks first, default "Don't restart". The port is free after
  restart (no "address in use"). Since #125.
- [ ] **R13 — update prompt and Help menu.** Publish a test release with notes: the prompt shows them
  as plain text with the releases link. Alt shows the menu bar; Help → Check for Updates, Report a
  Bug, Open Captures Folder (opens the capture drive), About all work; Ctrl+Shift+L/B/O work.
  Since #125.

### Diagnostics page in the packaged app
- [ ] **P10 — recipe dialogs and import/export.** In the packaged app, Save as (name + notes),
  Rename and Delete use the in-app dialog (Escape closes, focus returns to the button). Export a
  recipe, Import it back: it opens in the Save dialog; importing a hand-broken file is refused with
  a reason. The "modified since loaded" badge appears after editing an applied recipe.
  Since: this batch (PR TBD).
- [ ] **P10 — searchable picker on real data.** With the full campaign list, search, the Needs
  build / Built / Error chips and Group by (sample, campaign) work; campaign names appear for
  cuts that belong to one; Open in Plot lands on that cut and Directus opens the analysis record.
  Since: this batch (PR TBD).

### Plot on real cuts
- [ ] **X1 — Lite 3D height.** On a real cut, Lite 3D with Z = Fz shows height; picking a point and
  the linked marker land on the raised point. Since #123.
- [ ] **P2 — PNG/SVG export in the app.** Both downloads open, axes and units are right, a zoomed
  chart's ticks are distinct. Since #125.
- [ ] **P4 — difference vs reference.** Two passes of the same tool: Difference shows a sensible
  curve and mean/RMS only over the overlap of both crops. Since #124.
- [ ] **FFT overlay units.** With a filter profile on, the filtered FFT overlay sits on the main
  spectrum for an untouched band (both are "N rms" now). Since #125.
- [ ] **P6 — cutting metrics.** On a real turning cut with the operation sheet beside you: open
  Signal statistics (compute), then Cutting metrics. Check Fc, Pc and kc against a hand calculation
  from the sheet (vc = π·D·n/1000, Pc = Fc·vc/60, kc = Fc/(ap·f)) and the kc against the literature
  range for the material. Confirm the axis mapping per workholding and operation type on the rig
  (the owner's standard, the default, is Fc = Fx, Fp = Fz, Ff = Fy): pick the right mapping for
  each type and check it is remembered for that type only and the CSV `axis_map` matches. Check
  that an OD cut (`MT-O`) uses the Diameter box unchanged for vc and that a facing cut (`MT-F`, also one with a saved crop) uses D at the window midpoint,
  matching the radial axis of the plots. Check "—" with a reason on an
  operation with no feed or depth, and on a milling op. Since #127 (new default and per-subtype
  memory: this batch, PR TBD).

### Earlier issues that need the rig (from the 2026-10-02 batch)
- [ ] **#84** Real DAQmx error text and codes (‑200077); whether the chassis or the module limits the
  rate; coerced rates on discrete-rate modules.
- [ ] **#86** NI-DAQ hot-plug, and whether NI MAX simulated devices count as "present".
- [ ] **#109** Real Lab Amp latency.
- [ ] **#96, #101** Explorer reveal and network-drive behaviour on Windows.
- [ ] **#81** DAQ buffer overruns while a 12 GB finalize runs beside a live acquisition (held back:
  needs the chassis).
- [ ] **#90** Packaged NSIS build and the Tailscale update feed (held back).

## C. d1-server and infrastructure

- [ ] **Diag clustering is CPU-independent.** Rebuild a diagnostics analysis on `d1-server` for a cut
  built before 2026-10-06: cluster ids match the old result. (`scripts/diag/spatial.py` pins
  HDBSCAN's tie order; the goldens pass with and without AVX-512, but the server's CPU decides
  which side old results were built on.) Since #123.
- [ ] **filter-service `/fft` change deployed.** After redeploying the plugin, the Plot overlay reads
  in N rms (see the FFT check above). Since #125.
- [ ] **P10 — batch diagnostics build on d1-server.** In Diagnostics, tick 3 or more analysed cuts
  (at least one already built with the default recipe), Apply recipe to selected with a library
  recipe. Expect: the summary says queued / skipped; the orchestrator daemon processes every
  queued cut in turn until each shows built; no cut is queued twice. Since: this batch (PR TBD).
- [ ] **P10 — skipped cuts really match.** Apply the same recipe again to the same selection:
  everything is skipped as "already built with this recipe" and `diag_recipe_hash` /
  `updated_at` on those rows do not change. Then tick *Rebuild*: they requeue. Since: this batch (PR TBD).
- [ ] **P10 — build permissions by role.** As a Lab Member, Apply recipe to selected queues builds
  (Lab Member can update `machining_force_analysis`, migration 111). As a role with read-only access
  to analyses, it stops on the first item with "your role can't request builds" and nothing is queued. Since: this batch (PR TBD).
- [ ] **#80** MATLAB run on the d1-server orchestrator and Directus asset download (held back).
- [ ] **#10** Figure-mode PNGs re-baked by MATLAB for cuts with a saved crop (held back).
- [ ] **#97** Tailscale serve, phone access, live-DAQ load (held back; security model is an owner
  decision).

## Done

(Move ticked items here with their date and result.)
