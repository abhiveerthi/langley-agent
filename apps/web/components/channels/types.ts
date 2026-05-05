// Shared types for the team-channels surface. The shapes mirror the API
// contract being implemented in apps/api in parallel — keep them in sync.
//
// The backend is the source of truth: every field here is what the FE
// receives over the wire from the channels endpoints. We don't hide any
// fields the FE doesn't currently render so the components can opt in
// later (e.g. surfacing `agent_run_id` as a "see what produced this"
// affordance) without a type change.

export type Channel = {
  id: string;
  name: string;
  description: string | null;
  created_by: string | null;
  created_at: string;
  archived_at: string | null;
  member_count: number;
};

// Rich-card payload riding on the `metadata` jsonb column. Currently only
// the "approval" variant exists; future kinds (poll, brief preview, deal
// pitched) slot in here without a schema change. The variant lives in
// metadata so message search keeps working off the plain-text body — the
// body always carries a fallback description ("@brand-manager needs your
// approval to continue.") for both search and the no-card render path.
export type ChannelMessageMetadata =
  | Record<string, never>
  | {
      kind: "approval";
      approval_id: string;
      // Only present after a decision lands. Set by the channel approve/
      // reject endpoints which UPDATE the row in place; the realtime
      // UPDATE event drives the FE to swap the buttons for a static
      // "approved by @sean" tag.
      status?: "approved" | "rejected";
      reviewed_by?: string;
    };

export type ChannelMessage = {
  id: string;
  channel_id: string;
  org_id: string;
  sender_user_id: string | null;
  sender_agent_id: string | null;
  sender_user: {
    id: string;
    full_name: string | null;
    email: string;
  } | null;
  sender_agent: {
    id: string;
    slug: string;
    name: string;
    icon: string | null;
  } | null;
  body: string;
  mentioned_user_ids: string[];
  mentioned_agent_slugs: string[];
  agent_run_id: string | null;
  in_reply_to_message_id: string | null;
  metadata: ChannelMessageMetadata;
  created_at: string;
  edited_at: string | null;
};

export type MentionableAgent = {
  // `id` is the agents-table primary key. The autocomplete popover keys on
  // `slug`; this id field exists so the realtime resolver can match a
  // `sender_agent_id` from a `channel_messages` INSERT payload directly,
  // without round-tripping back to the API for the joined `sender_agent`.
  id: string;
  slug: string;
  name: string;
  icon: string | null;
};

export type MentionableUser = {
  id: string;
  full_name: string | null;
  email: string;
};

export type MentionableMaps = {
  agentsBySlug: Record<string, MentionableAgent>;
  agentsById: Record<string, MentionableAgent>;
  usersById: Record<string, MentionableUser>;
  // Pre-built arrays for the autocomplete popover so we don't recompute on
  // every keystroke. Sorted: agents alphabetically by slug, users by display
  // name (falling back to email).
  agents: MentionableAgent[];
  users: MentionableUser[];
};
