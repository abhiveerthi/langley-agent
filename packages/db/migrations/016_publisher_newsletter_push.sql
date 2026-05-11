-- Track when a package's newsletter draft was actually sent via Gmail.
-- Mirrors the youtube_pushed_at + x_posted_at columns for the newsletter
-- push flow. `newsletter_message_id` is Gmail's message id (returned by
-- users.messages.send), useful for "view in Gmail" deep links and dedup.

alter table publisher_packages
  add column if not exists newsletter_sent_at timestamptz,
  add column if not exists newsletter_message_id text;
