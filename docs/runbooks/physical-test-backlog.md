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

### Desktop shell
- [ ] **R11 — Restart recorder.** Kill the backend (Task Manager): the Doctor's "Restart recorder"
  brings it back and the doctor goes green. While recording: it refuses. With the backend hung
  (not answering, still running): it asks first, default "Don't restart". The port is free after
  restart (no "address in use"). Since #125.
- [ ] **R13 — update prompt and Help menu.** Publish a test release with notes: the prompt shows them
  as plain text with the releases link. Alt shows the menu bar; Help → Check for Updates, Report a
  Bug, Open Captures Folder (opens the capture drive), About all work; Ctrl+Shift+L/B/O work.
  Since #125.

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
  range for the material. Confirm which dynamometer axis really is the main cutting force, then fix
  the assumed default mapping (Fc=Fz, Ff=Fx, Fp=Fy) if it is wrong. Check "—" with a reason on an
  operation with no feed or depth, and on a milling op. Since: this batch (PR TBD).

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
- [ ] **#80** MATLAB run on the d1-server orchestrator and Directus asset download (held back).
- [ ] **#10** Figure-mode PNGs re-baked by MATLAB for cuts with a saved crop (held back).
- [ ] **#97** Tailscale serve, phone access, live-DAQ load (held back; security model is an owner
  decision).

## Done

(Move ticked items here with their date and result.)
