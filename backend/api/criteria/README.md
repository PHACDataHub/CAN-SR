# Criteria configuration backend contract

This module is the Phase 1 foundation for the extended criteria UI. It introduces
canonical criteria configuration without replacing existing screening consumers.

## Canonical storage

- `criteria`: strict `schema_version: 2` JSON.
- `criteria_yaml`: deterministic YAML generated from the same model.
- `criteria_parsed`: compatibility projection for current screening and extraction
  code, plus stable `items` with IDs.
- `criteria_revision`: optimistic concurrency token supplied as `expected_revision`.

All four values are updated atomically by the canonical save operation.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/sr/{sr_id}/criteria-config` | Canonical config or read-only legacy migration preview. |
| `POST` | `/sr/{sr_id}/criteria-config/validate` | Validate canonical JSON. |
| `POST` | `/sr/{sr_id}/criteria-config/import-yaml` | Parse v2 or legacy YAML without saving. |
| `PUT` | `/sr/{sr_id}/criteria-config` | Save with revision and invalidation guards. |
| `GET` | `/sr/{sr_id}/criteria-config/export-yaml` | Export deterministic v2 YAML. |

Validation failures return HTTP 422 with field paths. Stale revisions,
screening-data invalidation, and unconfirmed legacy migration return HTTP 409.

## Migration and compatibility

Legacy conversion is deterministic. IDs derive from source text with ordered
collision suffixes. Explicit `(exclude)` or `[exclude]` markers become `exclude`;
other answers default to `include`, with diagnostics for every inference.

Load and import operations never persist migration output. Any write of migration
output that contains inferred semantics must include the exact
`migration_fingerprint` returned by the current preview. This applies to review
creation, canonical save, and the compatibility YAML update endpoint.

Triggers may reference only earlier questions or selection parameters and must
target one of that source's options. Text parameters cannot be trigger sources.
The existing explicit `force` guard remains required when screening data exists.
