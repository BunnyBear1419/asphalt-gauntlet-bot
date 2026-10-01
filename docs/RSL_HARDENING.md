# RSL Hardening & Final-System Architecture

This pass centralizes safeguards shared by the Racing Syndicate League website and Discord bot.

## Competition recovery
Normal Gauntlet flow is CREATED -> ACCEPTED -> ACTIVE -> SUBMITTED -> VERIFIED -> SETTLED.
Recovery states are explicit: ABANDONED, EXPIRED, and RECONCILIATION_REQUIRED. A settled match cannot return to an active state.

## Economy reconciliation
The existing RSL ledger remains authoritative. A mismatch produces STAFF_APPROVAL_REQUIRED instead of silently changing a player's balance. Deterministic idempotency keys remain available for mutation references.

## Security and permissions
Capabilities are separated into system, players, moderation, tickets, gauntlet, tournaments, clubs, economy, media, and audit. Existing authorization code remains the enforcement owner.

## Proof integrity
SHA-256 fingerprints can be stored with proof submissions to identify duplicate/replayed evidence without modifying the original file.

## Privacy and notifications
Public profile data uses an allow-list. Quiet-hour evaluation supports overnight windows while existing notification preferences remain user-controlled.

## Abuse protection and retention
A deterministic fixed-window limiter and retention predicate are available to sensitive mutations and existing reliability cleanup jobs.

## Browser regression
Dedicated contract tests cover the Create Club, Player Settings, and Admin System controls that have recently reported failures. They verify the visible control, JavaScript binding, and API target stay connected.

The existing CI remains the final gate before Discloud deployment and rollback.
