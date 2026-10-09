# Post-rig reports batch — 2026-10-08

Plan for the in-app reports filed after the rig-day batch (#191–#197, all on 0.1.34), plus a
re-check of the older open reports (#10 #20 #30 #31 #64 #80 #81 #86 #90 #97 #100 #108). Triaged
against main `c016dfe` (0.1.35 in the changelog; release PR #224 still open). The rig-day issues
(#135–#137, #185–#190) are fixed on main and only wait for the rig re-checks. Delete this plan
once the batch has shipped (see `docs/superpowers/README.md`).

## 0. Already fixed

| # | Evidence |
|---|---|
| 195 (mostly) | `backend/app/channels.py:91-117` `autoassign()` already gives Fx1..Fz4 + Tacho on this chassis (slot-sorted, `nidaq_enum.py:121`), runs on first launch (`main.py:2742`) and is saved in `CONFIG_DIR/nidaq_channels.json`. The report's own machine state shows that mapping. Left open: see §2. |
| 31 (leftover) | Restoring a tombstoned backup now clears the tombstone (7a34058: `backup-server/server.py:443`, `backend/app/backup.py:146`). Needs the backup server redeployed. |
| 86 (rig part) | Chassis re-read every 5 s (c6bda01, #215). Rig re-check in the backlog. |

## 1. Needs real equipment or the server to confirm

| # | What only the real setup can confirm |
|---|---|
| 197 | Packaged Windows app: an update downloaded while on the login page shows no prompt; after sign-in the in-app prompt appears, Enter in a text field does not install |
| 108 | A pop-out whose mode/channels were changed reopens as changed after a relaunch |
| 30 | Settings tab change scroll (fixed in 0.1.33) confirmed on the rig PC |
| 81 | Held back: concurrent save and acquisition needs a multi-session model and DAQ-overrun tests |

## 2. Held back for an owner decision

- **#184** manual "start FRM now" (unchanged from the rig-day plan).
- **#194 (format)** long cuts get no .mat because MAT v5 can't hold a > 2 GB variable
  (`finalize.py:59`, float64 sizing at `:249-251`). Options: (a) MAT v7.3/HDF5 via h5py written in
  blocks (no cap; `scipy.io.loadmat` can't read it; new packaged dependency); (b) float32 force
  channels (~2× the limit, changes the DATA layout `process_force.m` expects); (c) split files.
  The wording fix ships here.
- **#195** beyond what exists: (b) a known-rig signature applied on first run, or (c) a pre-flight
  warning when saved bindings name ports missing from the scan, with one-click re-assign.
- **#197 (OS notifications while the app is closed)**: needs a background agent or scheduled task.
  Options: won't do / toast only while running minimised / scheduled-task checker.
- **#10** should Figure be re-baked with the saved crop (changes the summary's auto `cut_*_idx`)?
- **#20** screenshot attachments (GitHub App permission + privacy rule) — asked twice, unanswered.
- **#31** one list or two for backups/incomplete recordings, and which verbs.
- **#64** audio replay: fidelity (cache decimated without anti-aliasing) and non-1× speeds.
- **#80** what "processing" should produce; the crawler can't read app-uploaded .mat files.
- **#90** in-app downgrade: does the feed keep old installers, can old versions read new data.
- **#97** remote control: security model (auth, Tailscale only, read-only vs control).

## 3. This batch — work streams

Workers: `force-app-implementer` / `force-plotting-implementer` (Sonnet, high), one worktree
each under `.claude/worktrees/`. Workers don't edit the backlog, the changelog or the version.

### Status

| Stream | Scope | Worktree / branch | State |
|---|---|---|---|
| A — Record actions | #192 (P1), #194 wording (P2) | `agent-a618ae3a5960c5690` | merged (`6fb1529`, `de657c3`) |
| B — Update prompt | #197 (P2) | `agent-a26be31214eaecb5d` | merged (`8d607b8`, `1ebccc7`) |
| C — Plot loading + hover | #191 (P3), #100 slice (P3) | `agent-ae84af1c48ac989d7` | merged (`3d73761`, `6d5885f`); Full keeps a corner pill while streaming |
| D — Settings, pop-outs, login | #193 (P3), #108 (P2), #196 (P3) | `agent-a59e3ac952ddf81db` | merged (`b1266ce`, `c8eeecb`); #196 light login looks consistent, no change, needs the reporter's screenshot |
| Simplify, debug, review | /simplify, force-app-verify, force-app-reviewer (Opus) | main checkout | done: simplify `b89b23c`; debug all PASS, found a clipped Clear button; Opus review 2 should-fix + 5 optional, all fixed (`d4bbed9`..`e4f7d40`) |
| E — Manual FRM start | #184 | `batch2-e-frm-start` | merged (`6b08a5f`, `cc4d19d`) |
| F — MAT v7.3 for long cuts | #194 format | `batch2-f-mat73` | merged (`cbc015d`, `d6b8303`) |
| G — Channel check | #195 (c) | `batch2-g-channels` | merged (`655b20c`..`45eddd0`) |
| H — Update notifications | #197 (closed app) | `batch2-h-update-notify` | merged (`57ef258`..`3687507`); simplify `2c9ecf4`; Opus review: 6 should-fix + 3 optional, 8 fixed (`2cacd3d`..`9a40ee5`), skipped: longer finalize blocks the next cut; debug rerun after a usage-limit stop |
| Coordinator | changelog 0.1.36, backlog, preflight, PR #230 | main checkout | in progress |

### A. Record actions — #192, #194 wording
- **#192 cause:** in the done state `RecordingActions.vue:66-75` shows Start and New. New
  (`workspace.ts:699-718` `newRun()`) bumps `operation_sequence`, clears the auto Cut ID,
  `chips_ref`, `chips_collected`, `new_edge`, and doesn't record. Start (`requestStart()` →
  `start()`, `workspace.ts:352,569`) touches none of it, and the save dialog's "Open in Plot"
  (`SaveCutDialog.vue:211-216`) closes without `newRun()`. So save → Plot → back → Start records a
  cut with the previous cut's sequence, Cut ID, chips and new-edge.
- **Change:** in the done state Start reads "Start next cut" and runs `newRun()` then `start()`;
  New becomes "Clear for next cut" (tooltip: clears the per-cut fields without recording). Ctrl+N
  and the shortcut list stay consistent.
- **#194 wording:** `SaveCutDialog.vue:317` says only "exceeds size limit". Show the reason
  (`mat_skip_reason`), the limit in minutes at the capture's rate, and that raw, cache and CSV are
  kept.
- **Tests:** `workspace.test.ts`: finish a cut at sequence 3 with `new_edge`, `requestStart()` →
  payload has sequence 4, `new_edge` false, new Cut ID; pure helper for the .mat skip text.

### B. Update prompt — #197
- **Cause:** `desktop/src/updater.ts:64-90` shows a parentless native `showMessageBox` with
  `defaultId: 0` ("Update now") on `update-downloaded`, on any route including `/login`; it steals
  focus and Enter installs.
- **Change:** with a main window, push `{state:'downloaded', version, notes}` on the existing
  `update:status` channel; keep the native dialog only when there is no window; keep the recording
  re-check in `update:install`. New web `UpdatePrompt.vue` in the app's design, mounted in
  `AppShell.vue` (never on `/login`), doesn't take focus, default action "Not now". Add `notes`
  to `UpdateStatus` (`preload.ts`, `web/src/electronBridge.d.ts`).
- **Tests:** `updater.test.ts`: with a window, `showMessageBox` is not called and the window gets
  `update:status` downloaded + notes; vitest for the prompt's pure state helper.

### C. Plot loading + hover — #191, #100
- **#191 cause:** Lite (`FrmCloud.vue:1111`, centred veil, canvas hidden), Full (`FrmOctree.vue:690`,
  canvas visible then corner pill) and Figure (`ForceDashboard.vue:3179`, 160 px box) mount
  `LoadingOverlay` differently; the filtered-solo `FrmCloud` (`:3170`) emits no `@stage`.
- **Change:** one overlay at host level in `.frm-img` from `frmStage ?? figStage` via a pure
  `frmOverlay(mode, stage, figLoading)` in `loadStage.ts`; remove per-renderer overlays; wire
  `@stage` on the filtered-solo pane.
- **#100 slice:** `ForceChart.vue:307` `hoverPt` is read in the chart's own template (`:554`,
  `:583`), so each hover re-renders every path. Move crosshair/dot/tooltip into a child
  `ChartHoverLayer.vue`; the parent stops reading the hover index.
- **Tests:** `frmOverlay` gives the same variant for figure download, lite build, full open;
  hover changes don't re-render the parent (render counter).

### D. Settings, pop-outs, login — #193, #108, #196
- **#193:** `LogsSettings.vue:212,267-270` colours only the level. Pure `logCategory(r)` (error,
  warning, network = httpx/urllib3/"HTTP Request", ui = `force_app.client`, recording =
  session/finalize, other) shown as a coloured left border with theme tokens, plus a category
  filter. Test on sample lines.
- **#108:** `LivePanelWindow.vue:26-38` reads its URL once and never writes it back, while
  `desktop/src/popouts.ts:73-77` saves each pop-out's URL at quit. Shared `record/popoutQuery.ts`
  (build + parse); watch the panel state and `history.replaceState` the rebuilt query. Round-trip
  vitest.
- **#196:** no description. Take light and dark screenshots of `/login` with force-app-verify;
  suspects are the slate primary button (`styles.css:214`) and the aura (`LoginPage.vue:94-104`).
  Fix what is clearly inverted in `LoginPage.vue` only; otherwise leave the issue open for a
  screenshot.

### Second wave (owner decisions of 2026-10-08)

The owner chose: include #184; #194 long cuts as MAT v7.3; #195 option (c); #197 notifications
while the app is closed. Worktrees cut from the batch branch at `27ffa20`.

- **E #184:** `POST /record/cut-start` sets the live FRM cut origin now, as the detector would;
  FrmPanel shows "Start FRM now" while recording and waiting. Only while no start is detected (no
  re-origin). summary.json records the source (`auto`/`manual`). The saved crop is unchanged
  (finalize's post-hoc crop stays the reference). Detector threshold unchanged.
- **F #194:** captures over `MAT_MAX_BYTES` get a MAT v7.3 (HDF5) file written block by block with
  h5py, same variable names and layout as the v5 file; under the limit stays v5. Packaged backend
  bundles h5py. Note and Bake follow.
- **G #195:** pre-flight `channels` warns when saved bindings name ports missing from the scan,
  with one-click re-assign (existing autoassign).
- **H #197:** a Windows toast when an update has downloaded and the window isn't focused; a daily
  / at-logon scheduled check while the app is closed, with a Settings toggle.

## 4. After the streams merge

`/simplify`, debug pass (force-app-verify on the merged branch), Opus `force-app-reviewer` final
review, fix findings, preflight, changelog 0.1.36 + version bump, backlog items, PR, merge.
Closing issues and posting the owner questions wait for the user.
