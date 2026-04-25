-- Track when a package's social.twitter copy was actually posted to X.
-- Mirrors the youtube_pushed_at column for the X / Twitter push flow.

alter table publisher_packages
  add column if not exists x_posted_at timestamptz,
  add column if not exists x_tweet_id text;
