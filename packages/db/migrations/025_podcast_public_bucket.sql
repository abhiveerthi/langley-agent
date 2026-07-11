-- Content Agent Phase D: public podcast hosting bucket.
--
-- The podcast is self-hosted (product decision: no Transistor/Buzzsprout):
-- Spotify/Apple ingest a public RSS feed, and every episode's audio URL in
-- that feed must be world-readable. org-assets is private (RLS'd, member
-- reads via the API) so published episodes are COPIED into this public
-- bucket at publish time:
--
--   podcast-public/<org_id>/feed.xml            — the show's RSS feed
--   podcast-public/<org_id>/episodes/<video>.m4a — approved episode audio
--
-- Only APPROVED, PUBLISHED episodes ever land here — the pipeline's review
-- gate is what keeps drafts out of the public feed. Writes are service-role
-- only (the publish runner); public read is exactly the point.

insert into storage.buckets (id, name, public)
values ('podcast-public', 'podcast-public', true)
on conflict (id) do nothing;

-- Public buckets serve /object/public/ URLs without policies, but add an
-- explicit anon select policy so authenticated storage API reads work too.
do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname = 'storage' and tablename = 'objects'
      and policyname = 'public read podcast-public'
  ) then
    create policy "public read podcast-public"
      on storage.objects for select
      using (bucket_id = 'podcast-public');
  end if;
end $$;
