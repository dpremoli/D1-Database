# Security Policy

D1-Database stores scientific provenance and **export-controlled** material
metadata, and is the authentication backend for lab data-capture apps. Security
is a first-class concern, not a Phase 9 afterthought.

## Reporting

This repository is private. Report any suspected vulnerability or data exposure
privately to the maintainer (`dpremoli1@sheffield.ac.uk`) — do not open a public
issue.

## Standing rules

- **No secrets in git.** Configuration comes from `.env` (git-ignored); only
  `.env.example` (placeholders) is committed. Keys, certs, and dumps are ignored.
- **No real data in git.** Large experimental files (10–100 GB force data) live
  in MinIO and are referenced by URI — never committed. See `.gitignore`.
- **No plaintext passwords — ever.** The legacy `Users` sheet stored plaintext
  passwords (`docs/legacy-data-analysis.md`); these must be hashed on import and
  reset. Human credentials are hashed; machine/app nodes (MATLAB `ABFP`,
  plugins) authenticate via revocable API tokens.
- **Export control.** Honour `Export Controlled?` flags in the access/visibility
  model from day one — they may carry ITAR/ECJU obligations.
- **Audit everything.** All mutations to core entities are recorded in an
  append-only, trigger-based audit log (ADR-0003); it must not be bypassable.
- **Least privilege.** The text-to-SQL/LLM path uses a **read-only** Postgres
  role with a statement timeout and a view allow-list (Phase 6).

## Threat-model checkpoints

A dedicated security review runs in **Phase 9** (token revocation, RBAC
boundaries, MinIO bucket policy, SQL-injection surface incl. text-to-SQL, and
dependency scanning), but the rules above apply continuously.
