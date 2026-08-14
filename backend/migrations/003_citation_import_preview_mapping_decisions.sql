-- Durable, explicit import-preview mapping decisions. This is separate from
-- proposed_mapping so parser suggestions and user approval remain auditable.
ALTER TABLE citation_import_previews
    ADD COLUMN IF NOT EXISTS mapping_decision JSONB;
