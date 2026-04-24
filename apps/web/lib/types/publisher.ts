// Shapes returned by the Publisher API — mirrors the publisher_packages
// table in packages/db/migrations/003_publisher_packages.sql.

export type PublisherPackageStatus =
  | "generating"
  | "draft"
  | "pending_push"
  | "pushed";

export type PublisherChapter = { time: string; label: string };

export type PublisherSocial = {
  twitter?: string;
  newsletter?: string;
};

export type PublisherPackage = {
  id: string;
  org_id: string;
  video_id: string;
  video_title: string;
  status: PublisherPackageStatus;
  title_variants: string[];
  description: string | null;
  tags: string[];
  chapters: PublisherChapter[];
  pinned_comment: string | null;
  thumbnail_ideas: string[];
  social: PublisherSocial;
  warning: string | null;
  approval_id: string | null;
  youtube_pushed_at: string | null;
  created_at: string;
  updated_at: string;
};

export type PublisherApproval = {
  id: string;
  org_id: string;
  thread_id: string | null;
  requested_by_agent: string;
  action_type: "youtube_metadata_update";
  action_payload: {
    package_id: string;
    video_id: string;
    proposed_title: string;
    proposed_description: string;
    proposed_tags: string[];
    current_title: string;
    current_description: string;
    current_tags: string[];
  };
  preview: string;
  status: "pending" | "approved" | "rejected";
  created_at: string;
};

// Which fields can be regenerated through POST /packages/{id}/regenerate
export const REGEN_FIELDS = [
  "title_variants",
  "description",
  "tags",
  "chapters",
  "pinned_comment",
  "thumbnail_ideas",
  "social.twitter",
  "social.newsletter",
] as const;

export type RegenField = (typeof REGEN_FIELDS)[number];
