-- Tasks workspace — Monday.com-style Kanban surface at `/app/tasks`.
--
-- Adds the bits the existing `tasks` table didn't cover for a column-based
-- board view: a `deal_id` link so a Brand Manager deal can show its
-- subtasks (and tasks can filter by deal), a `position` int for ordering
-- within columns, and a per-org `task_statuses` list on `orgs` so each
-- tenant can later customize their column set without a schema change.
--
-- The status column on `tasks` itself stays free-text (already is) — the
-- `task_statuses` jsonb on `orgs` is the *display* list. Tasks can hold
-- any status string; the UI only renders columns for the org's chosen list
-- and groups orphaned-status tasks under "Other".

alter table tasks
  add column if not exists deal_id uuid references brand_deals(id) on delete set null,
  add column if not exists position int not null default 0;

create index if not exists idx_tasks_org_status_position
  on tasks (org_id, status, position);

-- Filter tasks by deal (used by Brand Manager dashboard's deal detail view
-- in a follow-up branch).
create index if not exists idx_tasks_deal
  on tasks (deal_id) where deal_id is not null;

-- Per-org status list. Default = standard Kanban columns; orgs that want
-- custom statuses (handled by a future settings UI) update this jsonb.
-- Stored as ordered array because column order is meaningful.
alter table orgs
  add column if not exists task_statuses jsonb not null
    default '["todo", "in_progress", "blocked", "done"]'::jsonb;
