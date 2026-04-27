-- Extend org_profiles with the richer brand fields the settings UI exposes.
--
-- The original 005 row was minimal (name, voice, primary_email) — enough to
-- bootstrap an org from OAuth signup. This adds the inputs that actually
-- shape agent output once the user fills them in:
--
--   - `brand_logo_url`       — for UI; not yet read by agents
--   - `brand_tagline`        — short one-liner, used in pitch headers + thumbnail copy
--   - `brand_about`          — short company description, available to every agent
--   - `brand_writing_sample` — 1-3 paragraphs in the user's voice, the strongest voice signal
--   - `brand_tone_keywords`  — short adjective list ("punchy, irreverent, no fluff")
--   - `brand_avoid_list`     — phrases/words the agents must never use
--   - `brand_default_cta`    — preferred CTA ("Subscribe", "Join the newsletter")
--   - `brand_audience_descriptor` — free-text override on the niche preset's audience
--
-- All nullable. The Pydantic Brand model in packages/agents/core/profile.py
-- mirrors these fields. Settings PATCH writes them; load_profile reads them
-- and threads them into each agent's system.j2.

alter table org_profiles
  add column if not exists brand_logo_url text,
  add column if not exists brand_tagline text,
  add column if not exists brand_about text,
  add column if not exists brand_writing_sample text,
  add column if not exists brand_tone_keywords jsonb not null default '[]',
  add column if not exists brand_avoid_list jsonb not null default '[]',
  add column if not exists brand_default_cta text,
  add column if not exists brand_audience_descriptor text;
