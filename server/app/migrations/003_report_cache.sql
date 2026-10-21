ALTER TABLE directory_sync ADD COLUMN snapshot_hash text NOT NULL DEFAULT '';
CREATE TABLE report_versions (day date PRIMARY KEY, revision bigint NOT NULL DEFAULT 1);
CREATE TABLE report_cache (
 scope text NOT NULL, day date NOT NULL, revision bigint NOT NULL, directory_hash text NOT NULL,
 data jsonb NOT NULL, updated_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(scope,day)
);
