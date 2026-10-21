CREATE TABLE departments (
 id uuid PRIMARY KEY, name text NOT NULL CHECK(length(btrim(name)) BETWEEN 1 AND 120),
 ldap_group_id uuid UNIQUE REFERENCES directory_groups(id), enabled boolean NOT NULL DEFAULT true,
 revision bigint NOT NULL DEFAULT 1, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX department_names ON departments(lower(name)) WHERE enabled;
CREATE TABLE department_memberships (
 group_id uuid NOT NULL REFERENCES departments(id), employee_id uuid NOT NULL REFERENCES employees(id),
 valid_from timestamptz NOT NULL DEFAULT now(), valid_to timestamptz,
 PRIMARY KEY(group_id,employee_id,valid_from), CHECK(valid_to IS NULL OR valid_to>=valid_from)
);
CREATE UNIQUE INDEX department_current_membership ON department_memberships(group_id,employee_id) WHERE valid_to IS NULL;
CREATE INDEX department_employee_time ON department_memberships(employee_id,group_id,valid_from);
INSERT INTO departments(id,name,ldap_group_id,enabled)
 SELECT id,name,id,is_department FROM directory_groups
 WHERE is_department OR id IN (SELECT group_id FROM department_heads);
INSERT INTO department_memberships SELECT m.* FROM group_memberships m JOIN departments d ON d.id=m.group_id;
ALTER TABLE department_heads DROP CONSTRAINT department_heads_group_id_fkey;
ALTER TABLE department_heads ADD FOREIGN KEY(group_id) REFERENCES departments(id);
CREATE TABLE structure_version (id integer PRIMARY KEY CHECK(id=1),revision bigint NOT NULL DEFAULT 1);
INSERT INTO structure_version(id) VALUES(1);
TRUNCATE report_cache;
