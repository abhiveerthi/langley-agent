// Channel-surface helpers. Kept dependency-free so they can be imported
// from any of the channel components without circular references.

import type { MentionableMaps, MentionableAgent, MentionableUser } from "./types";

/**
 * Slugify a free-text channel name to match the API regex
 * (`/^[a-z0-9_-]{1,64}$/`). The user types "Marketing Ideas!" — we send
 * "marketing_ideas". Lowercases, replaces whitespace runs with `_`, drops
 * everything else, then trims to 64.
 */
export function slugifyChannelName(input: string): string {
  return input
    .toLowerCase()
    .trim()
    .replace(/\s+/g, "_")
    .replace(/[^a-z0-9_-]/g, "")
    .slice(0, 64);
}

/**
 * Slugify a user display name into a mention token. Mirrors the channel
 * slugify in spirit but allows hyphens because human names commonly have
 * them (e.g. "@mary-jane"). Falls back to the email local-part when no
 * full_name is set.
 */
export function userMentionToken(user: MentionableUser): string {
  const base = (user.full_name || user.email.split("@")[0] || "user").trim();
  return base
    .toLowerCase()
    .replace(/\s+/g, "-")
    .replace(/[^a-z0-9_-]/g, "")
    .slice(0, 64) || "user";
}

/**
 * Render a relative timestamp the same way the BM dashboard does. Lifted
 * verbatim so the channels page reads like the rest of the app.
 */
export function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  const diff = Date.now() - then;
  const minutes = diff / 60_000;
  if (minutes < 1) return "Just now";
  if (minutes < 60) return `${Math.floor(minutes)}m ago`;
  const hours = minutes / 60;
  if (hours < 24) return `${Math.floor(hours)}h ago`;
  const days = hours / 24;
  if (days < 7) return `${Math.floor(days)}d ago`;
  if (days < 30) return `${Math.floor(days / 7)}w ago`;
  return new Date(iso).toLocaleDateString();
}

/**
 * Build the `MentionableMaps` lookup structure from the raw API response.
 * Used both on initial load and on channel switch so the realtime row
 * resolver always has fresh sender info available.
 */
export function buildMentionableMaps(
  agents: MentionableAgent[],
  users: MentionableUser[],
): MentionableMaps {
  const agentsBySlug: Record<string, MentionableAgent> = {};
  const agentsById: Record<string, MentionableAgent> = {};
  for (const a of agents) {
    agentsBySlug[a.slug] = a;
    agentsById[a.id] = a;
  }
  const usersById: Record<string, MentionableUser> = {};
  for (const u of users) usersById[u.id] = u;

  return {
    agentsBySlug,
    agentsById,
    usersById,
    agents: [...agents].sort((a, b) => a.slug.localeCompare(b.slug)),
    users: [...users].sort((a, b) => {
      const an = (a.full_name || a.email).toLowerCase();
      const bn = (b.full_name || b.email).toLowerCase();
      return an.localeCompare(bn);
    }),
  };
}

/**
 * Display label for a user in the message header: prefer full_name, fall
 * back to the email local-part so we never render a blank.
 */
export function userDisplayName(user: { full_name: string | null; email: string }): string {
  return user.full_name?.trim() || user.email.split("@")[0] || user.email;
}

/**
 * One-letter avatar initial for a user. Always uppercase, falls back to
 * `?` when no usable text is available so the avatar bubble is never empty.
 */
export function userInitial(user: { full_name: string | null; email: string }): string {
  const src = (user.full_name?.trim() || user.email.split("@")[0] || "?").trim();
  return (src[0] || "?").toUpperCase();
}
