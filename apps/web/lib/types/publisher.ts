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
  /** Legacy single-blob newsletter copy. New packages prefer the
   *  subject + body split below; this stays for backwards-compat. */
  newsletter?: string;
  newsletter_subject?: string;
  newsletter_body?: string;
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
  x_posted_at: string | null;
  x_tweet_id: string | null;
  created_at: string;
  updated_at: string;
};

export type PlatformId = "youtube" | "twitter" | "newsletter";

export type YoutubeApprovalPayload = {
  package_id: string;
  video_id: string;
  proposed_title: string;
  proposed_description: string;
  proposed_tags: string[];
  current_title: string;
  current_description: string;
  current_tags: string[];
};

export type XApprovalPayload = {
  package_id: string;
  video_id: string;
  proposed_tweet: string;
  tweet_char_count: number;
};

export type NewsletterApprovalPayload = {
  package_id: string;
  video_id: string;
  to: string;
  subject: string;
  body: string;
  body_word_count: number;
};

export type PublisherApproval =
  | {
      id: string;
      org_id: string;
      thread_id: string | null;
      requested_by_agent: string;
      action_type: "youtube_metadata_update";
      action_payload: YoutubeApprovalPayload;
      preview: string;
      status: "pending" | "approved" | "rejected";
      created_at: string;
    }
  | {
      id: string;
      org_id: string;
      thread_id: string | null;
      requested_by_agent: string;
      action_type: "x_post";
      action_payload: XApprovalPayload;
      preview: string;
      status: "pending" | "approved" | "rejected";
      created_at: string;
    }
  | {
      id: string;
      org_id: string;
      thread_id: string | null;
      requested_by_agent: string;
      action_type: "send_newsletter";
      action_payload: NewsletterApprovalPayload;
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
  "social.newsletter_subject",
  "social.newsletter_body",
] as const;

export type RegenField = (typeof REGEN_FIELDS)[number];
