// ── Core entity types (mirrors Supabase tables) ──

export type OrgPlan = "starter" | "growth" | "pro";
export type OrgMemberRole = "owner" | "admin" | "member" | "viewer";

export type ThreadStatus = "active" | "archived";
export type MessageRole = "user" | "assistant" | "tool" | "system";

export type AgentRunStatus = "running" | "completed" | "failed" | "paused" | "cancelled";
export type TaskStatus = "pending" | "running" | "paused" | "completed" | "failed" | "cancelled";
export type TaskPriority = "low" | "medium" | "high" | "urgent";
export type TaskType = "manual" | "agent" | "scheduled" | "recurring";

export type ApprovalStatus = "pending" | "approved" | "rejected" | "expired";
export type IntegrationProvider = "google" | "slack" | "youtube" | "monday" | "dropbox";
export type IntegrationStatus = "active" | "expired" | "revoked";
export type NotificationType = "task_complete" | "approval_needed" | "agent_error" | "mention";

// ── Entities ──

export interface Org {
  id: string;
  name: string;
  slug: string;
  plan: OrgPlan;
  settings: Record<string, unknown>;
  created_at: string;
}

export interface User {
  id: string;
  email: string;
  full_name: string | null;
  avatar_url: string | null;
  created_at: string;
}

export interface OrgMember {
  id: string;
  org_id: string;
  user_id: string;
  role: OrgMemberRole;
  created_at: string;
}

export interface Agent {
  id: string;
  org_id: string;
  name: string;
  slug: string;
  description: string | null;
  icon: string | null;
  capabilities: string[];
  tools: string[];
  config: Record<string, unknown>;
  is_system: boolean;
  active: boolean;
  created_at: string;
}

export interface Thread {
  id: string;
  org_id: string;
  user_id: string;
  agent_id: string | null;
  project_id: string | null;
  title: string | null;
  status: ThreadStatus;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface Message {
  id: string;
  thread_id: string;
  role: MessageRole;
  content: string | null;
  tool_calls: ToolCall[] | null;
  tool_results: ToolResult[] | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface ToolCall {
  id: string;
  tool: string;
  input: Record<string, unknown>;
  status: "running" | "success" | "error";
  output?: unknown;
  duration_ms?: number;
}

export interface ToolResult {
  tool_call_id: string;
  output: unknown;
  error?: string;
}

export interface AgentRun {
  id: string;
  org_id: string;
  thread_id: string | null;
  task_id: string | null;
  agent_id: string;
  status: AgentRunStatus;
  input: Record<string, unknown> | null;
  output: Record<string, unknown> | null;
  error: string | null;
  steps: AgentRunStep[];
  tool_calls: ToolCall[];
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  started_at: string;
  completed_at: string | null;
  metadata: Record<string, unknown>;
}

export interface AgentRunStep {
  node: string;
  input?: unknown;
  output?: unknown;
  started_at: string;
  completed_at?: string;
}

export interface Project {
  id: string;
  org_id: string;
  name: string;
  description: string | null;
  status: "active" | "completed" | "archived";
  color: string;
  icon: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface Task {
  id: string;
  org_id: string;
  project_id: string | null;
  thread_id: string | null;
  agent_id: string | null;
  created_by: string | null;
  title: string;
  description: string | null;
  status: TaskStatus;
  priority: TaskPriority;
  type: TaskType;
  input: Record<string, unknown>;
  output: Record<string, unknown> | null;
  scheduled_at: string | null;
  cron_expression: string | null;
  due_at: string | null;
  completed_at: string | null;
  requires_approval: boolean;
  approved_by: string | null;
  approved_at: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface Approval {
  id: string;
  org_id: string;
  run_id: string | null;
  task_id: string | null;
  thread_id: string | null;
  requested_by_agent: string | null;
  action_type: string;
  action_payload: Record<string, unknown>;
  preview: string | null;
  status: ApprovalStatus;
  reviewed_by: string | null;
  reviewed_at: string | null;
  expires_at: string | null;
  created_at: string;
}

export interface Notification {
  id: string;
  org_id: string;
  user_id: string;
  type: NotificationType;
  title: string;
  body: string | null;
  action_url: string | null;
  read: boolean;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface Integration {
  id: string;
  org_id: string;
  provider: IntegrationProvider;
  status: IntegrationStatus;
  scopes: string[];
  metadata: Record<string, unknown>;
  created_at: string;
}

// ── SSE Event Types ──

export type SSEEventType =
  | "token"
  | "tool_call_start"
  | "tool_call_end"
  | "agent_thinking"
  | "approval_requested"
  | "error"
  | "done";

export interface SSEEvent {
  type: SSEEventType;
  data: unknown;
}
