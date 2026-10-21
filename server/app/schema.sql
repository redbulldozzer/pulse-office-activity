CREATE TABLE IF NOT EXISTS schema_migrations (
    version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS devices (
    id uuid PRIMARY KEY, label text NOT NULL, hostname text,
    token_hash text NOT NULL UNIQUE, enabled boolean NOT NULL DEFAULT true,
    registered_at timestamptz NOT NULL DEFAULT now(), last_seen timestamptz,
    agent_version text
);
CREATE TABLE IF NOT EXISTS employees (
    id uuid PRIMARY KEY, realm text NOT NULL, principal text NOT NULL,
    domain_uid bigint NOT NULL, display_name text NOT NULL,
    enabled boolean NOT NULL, present boolean NOT NULL DEFAULT true,
    first_seen timestamptz NOT NULL DEFAULT now(), last_seen timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS account_bindings (
    employee_id uuid NOT NULL REFERENCES employees(id), realm text NOT NULL,
    principal text NOT NULL, domain_uid bigint NOT NULL,
    first_seen timestamptz NOT NULL DEFAULT now(), last_seen timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY(employee_id, realm, principal, domain_uid)
);
CREATE INDEX IF NOT EXISTS account_lookup ON account_bindings(realm,principal,domain_uid);
CREATE TABLE IF NOT EXISTS directory_groups (
    id uuid PRIMARY KEY, name text NOT NULL, present boolean NOT NULL DEFAULT true,
    is_department boolean NOT NULL DEFAULT false, last_seen timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS group_memberships (
    group_id uuid NOT NULL REFERENCES directory_groups(id),
    employee_id uuid NOT NULL REFERENCES employees(id),
    valid_from timestamptz NOT NULL DEFAULT now(), valid_to timestamptz,
    PRIMARY KEY(group_id, employee_id, valid_from)
);
CREATE UNIQUE INDEX IF NOT EXISTS current_membership ON group_memberships(group_id,employee_id) WHERE valid_to IS NULL;
CREATE TABLE IF NOT EXISTS directory_sync (
    id integer PRIMARY KEY CHECK(id=1), last_success timestamptz,
    last_attempt timestamptz NOT NULL, error text, users_count integer, groups_count integer
);
CREATE TABLE IF NOT EXISTS events (
    event_id uuid PRIMARY KEY, device_id uuid NOT NULL REFERENCES devices(id),
    employee_id uuid REFERENCES employees(id), resolution text NOT NULL,
    start_at timestamptz NOT NULL, end_at timestamptz NOT NULL,
    duration_ms bigint NOT NULL CHECK(duration_ms>=0), state text NOT NULL,
    key_presses integer NOT NULL CHECK(key_presses>=0),
    boundary_key_drops integer NOT NULL CHECK(boundary_key_drops>=0),
    payload jsonb NOT NULL, payload_hash text NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now(), CHECK(end_at>=start_at)
);
CREATE INDEX IF NOT EXISTS events_employee_time ON events(employee_id,start_at);
CREATE INDEX IF NOT EXISTS events_device_time ON events(device_id,start_at);
CREATE INDEX IF NOT EXISTS events_pending_identity ON events(resolution) WHERE resolution='unresolved_domain';
INSERT INTO schema_migrations(version) VALUES(1) ON CONFLICT DO NOTHING;
