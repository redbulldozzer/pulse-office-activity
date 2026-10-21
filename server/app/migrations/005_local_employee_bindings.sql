CREATE TABLE local_employee_bindings (
 id uuid PRIMARY KEY, device_id uuid NOT NULL REFERENCES devices(id),
 local_user text NOT NULL, local_uid bigint NOT NULL, employee_id uuid NOT NULL REFERENCES employees(id),
 valid_from timestamptz NOT NULL DEFAULT now(), valid_to timestamptz,
 CHECK(valid_to IS NULL OR valid_to>=valid_from)
);
CREATE UNIQUE INDEX local_binding_current ON local_employee_bindings(device_id,local_user,local_uid) WHERE valid_to IS NULL;
CREATE INDEX local_binding_history ON local_employee_bindings(device_id,local_user,local_uid,valid_from);
CREATE INDEX local_account_events ON events(device_id,start_at) WHERE payload->'identity'->>'account_type'='local';
