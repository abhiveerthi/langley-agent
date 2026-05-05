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
