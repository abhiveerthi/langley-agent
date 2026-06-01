-- Multi-step (sequential) approval chains.
--
-- Until now an `approvals` row represented a single-approver gate: one human
-- approve → resume the graph → write executes. The product roadmap's Agent #5
-- needs an ORDERED chain ("Kaydi approves, then Braden approves, then
-- auto-publish"), so a gate can require N sequential approvals where each step
-- must be satisfied in order before the graph resumes.
--
-- We model each STEP of a chain as its own `approvals` row (so the existing
-- list_pending / approve / reject / audit-trail machinery keeps working
-- unchanged per step). These columns let a row describe its place in the
-- chain. All are nullable / defaulted so:
--   - existing rows are untouched (chain = NULL, step_index = 0),
--   - single-step gates keep inserting exactly as before (chain stays NULL),
--   - only true multi-step gates populate `chain`.

alter table approvals
  -- Ordered list of approver role labels for the whole gate, e.g.
  -- ["reviewer", "owner"]. NULL for legacy / single-step approvals.
  add column if not exists chain jsonb,
  -- Which step of `chain` this row represents (0-based). Defaults to 0 so the
  -- single-step flow needs no special handling.
  add column if not exists step_index int not null default 0,
  -- The role label for this step (mirrors chain[step_index]); lets the UI show
  -- "Reviewer approval (1 of 2)" without re-deriving from chain. NULL for
  -- legacy single-step rows.
  add column if not exists approver_role text;

-- RLS is already enabled on `approvals` (migration 001) and the existing
-- "members can read/update own org approvals" policies are column-agnostic —
-- they gate on org_id, so they automatically cover these new columns. No new
-- policy needed; we intentionally do NOT alter the existing ones.
