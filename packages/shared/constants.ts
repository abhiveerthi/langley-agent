export const SYSTEM_AGENTS = ["general", "content-research"] as const;

export const TASK_STATUS_ORDER: Record<string, number> = {
  pending: 0,
  running: 1,
  paused: 2,
  completed: 3,
  failed: 4,
  cancelled: 5,
};

export const PRIORITY_ORDER: Record<string, number> = {
  urgent: 0,
  high: 1,
  medium: 2,
  low: 3,
};

export const MODEL_COSTS = {
  "claude-haiku-4-5-20251001": { input: 0.80, output: 4.00 }, // per 1M tokens
  "claude-sonnet-4-6-20260401": { input: 3.00, output: 15.00 },
} as const;

export const APPROVAL_REQUIRED_TOOLS = [
  "gmail_send",
  "slack_post_message",
  "slack_create_channel",
  "youtube_upload_video",
  "youtube_update_video",
  "gcal_create_event",
] as const;
