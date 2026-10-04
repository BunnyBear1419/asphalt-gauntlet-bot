# RSL Asset Rights Policy

## Purpose

Racing Syndicate League (RSL) is an independent community project. This policy governs third-party game imagery, especially Asphalt Legends imagery.

## Allowed asset sources

An image may be committed to the repository only when its source and permission basis are documented:

1. Original RSL artwork created for RSL.
2. RSL-owned artwork for which the project has the necessary rights.
3. User-submitted media when the submitting user confirms they have the right to provide it for the stated RSL use.
4. Officially licensed or written-authorized assets with the authorization retained by the project operator.
5. Official creator-program assets only when the project/account is actually eligible and the specific use is permitted by the current program rules.

## Prohibited by default

Do not commit or redistribute extracted game files, ripped textures/models, scraped images without a documented license/permission, official logos/promotional artwork merely because they are publicly viewable, assets whose license cannot be verified, or assets altered in a way prohibited by their license or authorization.

A non-affiliation disclaimer does **not** grant permission.

## Required metadata

Every third-party asset must have an entry in `web/static/assets/rsl/asset-rights.json` containing its path, source URL, rights basis, rights holder, allowed use, attribution requirement, modification permission, verification date, and notes or authorization reference.

Do not record private authorization documents or secrets in the public repository. Store those privately and reference them by an internal identifier.

## Removal rule

If permission expires, is revoked, cannot be verified, or a rights holder requests review, disable/remove the asset from public delivery until the rights position is resolved.

## Design fallback

Every protected or uncertain asset must have an original RSL fallback. The site should continue to work without third-party imagery.

## Legal note

This is an engineering/content-governance policy, not legal advice. Rights can depend on the exact asset, source, license, jurisdiction, and use.
