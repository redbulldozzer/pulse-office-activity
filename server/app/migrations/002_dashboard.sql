CREATE TABLE dashboard_sessions (
 token_hash text PRIMARY KEY, employee_id uuid NOT NULL REFERENCES employees(id),
 csrf_token text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
 expires_at timestamptz NOT NULL DEFAULT now()+interval '8 hours',
 last_seen timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE department_heads (
 group_id uuid NOT NULL REFERENCES directory_groups(id),
 employee_id uuid NOT NULL REFERENCES employees(id), PRIMARY KEY(group_id,employee_id)
);
CREATE TABLE dashboard_audit (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 actor_id uuid REFERENCES employees(id), action text NOT NULL, details jsonb NOT NULL,
 created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE login_attempts (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
 account_hash text NOT NULL, address text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX login_attempts_time ON login_attempts(created_at);
CREATE INDEX events_end_time ON events(end_at);
CREATE INDEX memberships_employee_time ON group_memberships(employee_id,group_id,valid_from);
