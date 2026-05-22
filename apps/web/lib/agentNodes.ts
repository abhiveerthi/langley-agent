/**
 * Human-readable labels for LangGraph node names emitted by the
 * orchestrator's `agent_thinking` SSE events. The backend sends the raw
 * node name (e.g. `research_target_brand`); the chat surfaces this through
 * `humanizeAgentNode` so the indicator reads like "Researching the
 * brand…" instead of like a function call.
 *
 * Keep the keys narrow — only nodes that actually run long enough to be
 * worth surfacing should appear. Anything missing falls through to the
 * title-cased fallback, which is fine for new agents until we tune
 * copy for them.
 */
const NODE_LABELS: Record<string, string> = {
  // Brand Manager
  fetch_media_kit: "Pulling your media kit",
  research_target_brand: "Researching the brand",
  draft_pitch: "Drafting the pitch",
  extract_email: "Formatting the email",
  revise_pitch: "Revising the pitch",
  send_email: "Sending",
  research_agent: "Researching",
  research_tools: "Looking things up",

  // Publisher
  fetch_video_details: "Pulling the video details",
  fetch_transcript: "Reading the transcript",
  generate_package: "Generating the package",
  persist_package: "Saving the package",
  push_metadata: "Updating YouTube",
  push_tweet: "Posting to X",
  push_newsletter_node: "Sending the newsletter",
  draft_newsletter: "Drafting the newsletter",

  // Strategist
  collect_signal: "Collecting signal",
  rank_ideas: "Ranking ideas",
  compose_brief: "Composing the brief",
  research_topic: "Researching",

  // Community Manager
  fetch_comments: "Reading comments",
  draft_reply: "Drafting the reply",
  classify_comment: "Reading the room",
};

export function humanizeAgentNode(node: string | null | undefined): string {
  if (!node) return "Thinking";
  const mapped = NODE_LABELS[node];
  if (mapped) return mapped;
  // Fallback: snake_case → Title Case. Reads less natural than the curated
  // map above but covers any node we haven't tuned copy for yet.
  return node
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}
