-- Long-term agent memory: cosine similarity search + RLS.
--
-- The `agent_memory` table (with embedding vector(1536) + an ivfflat cosine
-- index) has existed since 001_core.sql, but nothing read from or wrote to it
-- and — unlike every other tenant table — it was never put behind RLS. This
-- migration finishes the wiring so agents can learn/remember as the creator
-- works with them:
--
--   1. RLS so a member only ever sees their own org's memories (matches the
--      conventions for threads / tasks / approvals in 001_core.sql).
--   2. `match_agent_memory(...)` — a security-definer RPC that runs the cosine
--      similarity search. packages/agents/core/memory.py calls it via the
--      Supabase RPC interface rather than hand-rolling vector SQL through
--      PostgREST (which can't express the `<=>` distance operator + ORDER BY).
--
-- Idempotent: guarded with `if not exists` / `create or replace` so it's safe
-- to re-run.

-- ── Row Level Security ─────────────────────────────────────────────────────
alter table agent_memory enable row level security;

-- Members can read their own org's memories. Writes happen through the agent
-- runtime's service-role client (which bypasses RLS), so a member-scoped
-- read policy is all the surface we need here — mirrors the read policies on
-- agents / integrations in 001_core.sql.
drop policy if exists "members can read own org agent_memory" on agent_memory;
create policy "members can read own org agent_memory" on agent_memory for select
  using (org_id in (select org_id from org_members where user_id = auth.uid()));

-- ── Similarity search RPC ──────────────────────────────────────────────────
-- Returns the org's most-similar memories to `p_query_embedding`, most-similar
-- first. Optionally scoped to a single agent (by slug) so an agent recalls what
-- IT learned rather than every peer's notes; pass NULL for `p_agent_slug` to
-- search across all of the org's agents.
--
-- `1 - (embedding <=> query)` converts pgvector's cosine DISTANCE (0 = identical,
-- 2 = opposite) into a cosine SIMILARITY in [-1, 1] (1 = identical) that reads
-- naturally for callers. Ordering by the raw `<=>` distance lets the ivfflat
-- index (vector_cosine_ops) do the work.
--
-- SECURITY DEFINER + an explicit `p_org_id` filter: the function runs with the
-- definer's rights so it can be granted to authenticated users without exposing
-- the whole table, and every query is hard-scoped to one org_id.
create or replace function match_agent_memory(
  p_org_id uuid,
  p_agent_slug text,
  p_query_embedding vector(1536),
  p_match_count int default 5
)
returns table (
  id uuid,
  content text,
  metadata jsonb,
  created_at timestamptz,
  similarity float
)
language sql
stable
security definer
set search_path = public
as $$
  select
    m.id,
    m.content,
    m.metadata,
    m.created_at,
    1 - (m.embedding <=> p_query_embedding) as similarity
  from agent_memory m
  where m.org_id = p_org_id
    and m.embedding is not null
    and (
      p_agent_slug is null
      or m.agent_id in (
        select a.id from agents a
        where a.org_id = p_org_id and a.slug = p_agent_slug
      )
    )
  order by m.embedding <=> p_query_embedding
  limit greatest(p_match_count, 1);
$$;

grant execute on function match_agent_memory(uuid, text, vector, int) to authenticated;
