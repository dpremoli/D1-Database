# Rotating cutting-force dynamometer (RCD)

Reference constants pulled from the Kistler manuals read for
`docs/superpowers/specs/2026-09-07-milling-path-models-and-polar-design.md`, so they don't live
only in a PDF. Two devices are covered: the current RCD Type 9170B (wireless) and the older
9123C + 5223B charge-amplifier system (wired, analog).

## Components and ranges (9170B)

4-component: Fx, Fy, Fz, Mz. Coordinate frame **rotates with the tool**.

| | Nominal | Range 1 | Range 2 | Range 3 | Range 4 |
|---|---|---|---|---|---|
| Fx, Fy | -5..5 kN | -0.5..0.5 kN | -1..1 kN | -2.5..2.5 kN | -5..5 kN |
| Fz | -20..20 kN | -2.5..2.5 kN | -5..5 kN | -10..10 kN | -20..20 kN |
| Mz | -210..210 N·m | -10..10 N·m | -20..20 N·m | -50..50 N·m | -100..100 N·m |

Sampling rate 2.5 / 5 / 10 kHz per channel (not separately selectable); resolution 16-bit; max
speed 16,000 1/min. (9170B manual, chapter 10.)

## Feed force is not measured directly

The RCD gives Fx/Fy/Fz/Mz in the **rotating tool frame**. Feed force `Ff` and normal feed force
`FfN` are recovered by rotating Fx/Fy through the immersion angle phi:

```
Ff  =  Fx*sin(phi) + Fy*cos(phi)
FfN = -Fx*cos(phi) + Fy*sin(phi)
```

Only at phi=90 degrees do the rotating and fixed frames coincide (`Ff=Fx`, `FfN=Fy`). See
`packages/force-plotting/src/angle.ts`'s `toFixedFrame`. (9170B manual, chapter 8.1.1, Fig. 36/37.)

## Natural frequency and the tooth-passing rule

Tooth-passing frequency: `f = (n/60) * N`, where `n` is spindle speed in 1/min and `N` is the
number of cutting edges. Keep it below `f_n/5` for <5% amplitude error, or `f_n/3` for <10%.

Natural frequencies: approx. 2000 Hz (X/Y) and approx. 5300 Hz (Z) for a bare 9170B with the
HSK-A63 integrated adapter, no tool. Once installed in a real spindle with a tool attached, the
older 9123C measured 400-500 Hz in practice — the spindle/tool assembly's natural frequency
dominates, not the sensor's own. (9170B manual, chapters 6.3-6.4, 10.1; 9123C manual, chapter 5.4.)

## Drift mechanisms (all three affect Fz most)

- **Centrifugal**: Fz grows with the square of spindle speed (approx. `32,678*n^2 - 52.67*n` N in
  the manual's example, `n` in thousands of rpm) — radial forces Fx/Fy are largely unaffected.
  Minimise by bringing the spindle to speed *before* starting the measurement ("Operate").
- **Temperature**: non-linear drift, Z direction most sensitive. Minimise by thermally
  stabilising the system for at least 30 minutes before measuring, and letting the spindle run at
  the target speed beforehand.
- **Internal coolant pressure**: Fz drifts roughly linearly with coolant pressure, down to about
  -1600 N at 70 bar (the maximum permitted pressure). Minimise by starting coolant flow before
  "Operate" and holding pressure constant during the cut.

(9170B manual, chapter 7.)

## Zero-count / index-pulse channel (9123C + 5223B only)

Channel 6 on the 5223B2 signal conditioner: an infrared light barrier senses a groove on a
rotatable ring, alignable to a specific tool cutting edge — giving tooth *identity*, not just
angle. Needs a minimum 4000 Hz sampling rate, while the force channels 1-5 have a 1000 Hz
anti-aliasing filter — a materially different acquisition path from the force channels.
Not implemented in the force app; see `AngleSourceUnavailableError` in
`packages/force-plotting/src/angle.ts`. (9123C manual, chapters 5.6, 5.8.)

## Analog interface (9123C + 5223B)

+/-10 V on channels 1-5, +5 V on channel 6, D-Sub 15-pole connector, **differential** wiring (the
A/D card must run in DIFFERENTIAL, not SINGLE ENDED, mode to avoid ground-loop problems). RS-232C
for range selection and reset. (9123C manual, chapter 5.8.)
