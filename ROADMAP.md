# AgentOS — Feature Roadmap

Granular implementation tasks organized by phase. Each task is scoped for a single PR / work session.

---

## Phase 1 — Foundation (Week 1-2)
**Goal: Working chat that streams from a real agent. Deployable.**

### 1.1 Monorepo Setup
- [ ] Init Turborepo with pnpm workspaces (`turbo.json`, root `package.json`)
- [ ] Create `apps/web` — scaffold Next.js 16 App Router with TypeScript
- [ ] Create `apps/api` — scaffold FastAPI project with Poetry (`pyproject.toml`, `main.py`)
- [ ] Create `packages/shared` — shared TS types + Pydantic models
- [ ] Create `packages/db` — DB client stubs for both TS and Python
- [ ] Add `.env.example` with all env vars from PRD
- [ ] Add `docker-compose.yml` for local Postgres + Redis
- [ ] Verify `pnpm dev` runs both web + api concurrently via Turborepo

### 1.2 Database & Auth
- [ ] Create Supabase project (or local Supabase via CLI)
- [ ] Write migration `001_core.sql` — all core tables from PRD Section 7 (orgs, users, org_members, agents, threads, messages, agent_runs, projects, tasks, approvals, notifications, integrations, usage_log, agent_memory)
- [ ] Add RLS policies for all tenant-scoped tables
- [ ] Add indexes from PRD
- [ ] Enable pgvector extension for `agent_memory`
- [ ] Configure Supabase Auth (email/password + Google OAuth provider)
- [ ] Create seed script: default org, test user, system agents (general, content-research)

### 1.3 Frontend Auth & App Shell
- [ ] Install and configure Supabase client (`lib/supabase.ts` — browser + server clients)
- [ ] Build `/login` page — email/password + Google OAuth button
- [ ] Build `/signup` page — creates user + personal org
- [ ] Add auth middleware (Next.js middleware.ts) — redirect unauthenticated to `/login`
- [ ] Build app shell layout `(app)/layout.tsx` — sidebar + main content area
- [ ] Build `Sidebar.tsx` — nav links (Chat, Agents, Tasks, Projects, Runs, Dashboard, Settings), recent threads list, "New Chat" button
- [ ] Build `TopBar.tsx` — org name, user avatar, notification bell placeholder
- [ ] Install shadcn/ui + Tailwind, configure theme
- [ ] Add Zustand stores: `chat.ts` (threads, messages, active thread), `ui.ts` (sidebar state)

### 1.4 Backend Auth & Core API
- [ ] FastAPI app entry (`main.py`) — CORS, lifespan, include routers
- [ ] Auth middleware (`middleware/auth.py`) — validate Supabase JWT, extract `user_id` + `org_id`
- [ ] FastAPI dependency `get_current_user` — returns user context with org_id
- [ ] DB client (`packages/db/client.py`) — async Supabase client wrapper (or asyncpg)
- [ ] Health check endpoint `GET /api/health`
- [ ] Thread CRUD endpoints:
  - `POST /api/chat/threads` — create thread
  - `GET /api/chat/threads` — list threads for org
  - `GET /api/chat/threads/:id` — get thread with messages
  - `DELETE /api/chat/threads/:id` — archive thread

### 1.5 General Assistant Agent
- [ ] Implement `BaseAgent` class (`packages/agents/core/base.py`) — StateGraph scaffold, checkpointer setup, `run()`, `resume()`, `get_state()`
- [ ] Implement `BaseAgentState` TypedDict (messages, org_id, user_id, thread_id, task_id, metadata)
- [ ] Build General Assistant agent (`packages/agents/general/agent.py`) — basic ReAct graph with LLM node + tool node
- [ ] Add 2-3 starter tools: `web_search` (via Tavily or SerpAPI), `get_current_time`, `calculator`
- [ ] Write system prompt (`packages/agents/general/prompts.py`)
- [ ] Create `manifest.json` for General Assistant
- [ ] Build agent registry (`packages/agents/registry.py`) — `AGENT_REGISTRY`, `get_agent()`, `register_agent()`

### 1.6 SSE Streaming Chat
- [ ] Build SSE chat endpoint `POST /api/chat/stream` — accepts message + thread_id + agent_slug, returns `StreamingResponse`
- [ ] Map LangGraph stream events to UI events: `token` (streaming text), `tool_call_start`, `tool_call_end`, `agent_thinking`, `error`, `done`
- [ ] Persist user message to `messages` table before streaming
- [ ] Persist assistant message to `messages` table after stream completes
- [ ] Build `useChat` hook (`hooks/useChat.ts`) — manages SSE connection, parses events, updates Zustand store
- [ ] Build SSE client utility (`lib/sse.ts`) — EventSource wrapper with reconnect, typed event parsing

### 1.7 Chat UI
- [ ] Build `ChatWindow.tsx` — container with thread header, message list, input
- [ ] Build `MessageList.tsx` — renders list of messages, auto-scrolls to bottom
- [ ] Build `MessageBubble.tsx` — user messages (right-aligned) + assistant messages (left-aligned, streaming markdown with syntax highlighting via `react-markdown` + `rehype-highlight`)
- [ ] Build `ChatInput.tsx` — text input with send button, Enter to send, Shift+Enter for newline
- [ ] Build `AgentThinking.tsx` — animated typing indicator with current node name
- [ ] Wire up `/chat` page — new chat view, creates thread on first message
- [ ] Wire up `/chat/[threadId]` page — loads existing thread, resumes conversation
- [ ] Sidebar: populate recent threads list from API, click to navigate

### 1.8 Initial Deploy
- [ ] Dockerfile for FastAPI (`apps/api/Dockerfile`)
- [ ] Deploy frontend to Vercel — configure env vars
- [ ] Deploy API to Railway (or Render) — configure env vars, expose port
- [ ] Run migrations against production Supabase
- [ ] Smoke test: end-to-end chat flow on deployed URL

---

## Phase 2 — Agents + Visibility (Week 3-4)
**Goal: Tool calls visible in chat, runs are inspectable, tasks are tracked.**

### 2.1 Tool Call UI
- [ ] Build `ToolCallCard.tsx` — collapsible card: tool name + icon, status badge (running/success/error), input params (collapsed), output/result (collapsed), duration
- [ ] Update `MessageList` to render tool call cards inline between assistant messages
- [ ] Wire SSE events `tool_call_start` and `tool_call_end` to render/update tool call cards in real-time
- [ ] Build `ErrorCard.tsx` — red border, error message, retry button

### 2.2 Run Tracking
- [ ] Implement `RunTracker` middleware (`packages/agents/core/tracker.py`) — wraps agent runs, captures all step/tool events, persists to `agent_runs`
- [ ] Create `agent_runs` record at start of every chat stream
- [ ] Incrementally update `agent_runs.steps` and `agent_runs.tool_calls` as events fire
- [ ] Track token usage + cost per run (`input_tokens`, `output_tokens`, `cost_usd`)
- [ ] Set run status to `completed` or `failed` on finish
- [ ] API endpoints:
  - `GET /api/runs` — list runs for org (filterable by agent, status, date)
  - `GET /api/runs/:id` — get run detail with full step timeline

### 2.3 Pipeline Inspector UI
- [ ] Build `/runs` page — table of all agent runs with status badges, agent name, duration, cost, date
- [ ] Add filters: status, agent, date range
- [ ] Build `/runs/[id]` page — the inspector
- [ ] Build `RunTimeline.tsx` — vertical timeline of steps (START, node executions, tool calls, END)
- [ ] Build `StepCard.tsx` — expand/collapse, shows node name, input/output JSON, duration
- [ ] Build `ToolCallDetail.tsx` — within step card, shows tool input/output, duration
- [ ] Add cost + token breakdown summary at top of run detail
- [ ] Add "Cancel" button for running runs (calls `POST /api/runs/:id/cancel`)

### 2.4 Content Research Agent
- [ ] Build Content Research agent (`packages/agents/content-research/agent.py`) — multi-step graph: router → web_search → youtube_search → synthesize → generate_outline
- [ ] Implement tools: `web_search(query)`, `youtube_search(query, max_results)`
- [ ] Write system prompt focused on YouTube content research
- [ ] Create `manifest.json` for Content Research agent
- [ ] Register in `AGENT_REGISTRY`
- [ ] Test end-to-end: chat with content research agent, see tool calls, inspect run

### 2.5 Agent Management
- [ ] API endpoints:
  - `GET /api/agents` — list agents for org
  - `PATCH /api/agents/:slug/config` — update agent config (model, temperature, custom instructions)
  - `PATCH /api/agents/:slug/toggle` — enable/disable agent for org
- [ ] Build `/agents` page — agent gallery with cards (name, icon, description, capabilities, run count, status toggle)
- [ ] Build `/agents/[slug]` page — agent detail: description, capabilities, tools list, config panel, run history summary
- [ ] Add agent selector in chat input — `@agent-name` mention or dropdown to switch agent

### 2.6 Task Management
- [ ] API endpoints:
  - `GET /api/tasks` — list tasks (filterable by status, agent, project, priority)
  - `POST /api/tasks` — create task manually
  - `PATCH /api/tasks/:id` — update task (status, priority, assignment)
  - `POST /api/tasks/:id/run` — trigger agent run for a task
  - `POST /api/tasks/:id/cancel` — cancel running task
- [ ] Auto-create task when agent starts a run from chat (link task ↔ thread ↔ run)
- [ ] Build `/tasks` page — task list table with status badges, agent avatar, priority, date
- [ ] Add filters: status, agent, project, priority, date range
- [ ] Add sort: created, due date, priority, status
- [ ] Build `/tasks/[id]` page — task detail: title, description, agent, input/output JSON, run history, linked thread, status timeline
- [ ] Build `TaskCreatedCard.tsx` — inline card in chat when agent creates a task

---

## Phase 3 — Human-in-the-Loop + Approvals (Week 5)
**Goal: Agents pause for approval before consequential actions.**

### 3.1 Approval Backend
- [ ] Wire `interrupt_before` in `BaseAgent` — nodes listed in manifest's `interrupt_before` pause the graph
- [ ] On interrupt: create `approvals` record (action_type, action_payload, preview, status=pending, expires_at)
- [ ] API endpoints:
  - `GET /api/approvals` — list pending approvals for org
  - `POST /api/approvals/:id/approve` — approve action, resume graph
  - `POST /api/approvals/:id/reject` — reject action, continue graph with rejection
- [ ] Implement `BaseAgent.resume()` — updates graph state and continues execution
- [ ] Create notification on approval request (type: `approval_needed`)

### 3.2 Approval UI
- [ ] Build `ApprovalCard.tsx` — prominent card in chat: "Waiting for your approval" header, human-readable description, preview of action, Approve/Reject buttons
- [ ] Wire SSE event `approval_requested` to render ApprovalCard in chat
- [ ] On approve/reject: call API, update card state (approved/rejected), agent resumes streaming
- [ ] Build `/approvals` page — queue of all pending approvals across org, with approve/reject actions
- [ ] Add approval history to task detail page

### 3.3 Real-time Approval Notifications
- [ ] Set up Supabase Realtime subscriptions (`hooks/useRealtime.ts`)
- [ ] Subscribe to `approvals` table INSERT events for org
- [ ] On new approval: show toast notification + update bell badge count
- [ ] Subscribe to `tasks` table UPDATE events — live status changes in task list

---

## Phase 4 — Projects + KPIs (Week 6)
**Goal: Work is organized into projects, performance is measurable.**

### 4.1 Project Management Backend
- [ ] API endpoints:
  - `GET /api/projects` — list projects for org
  - `POST /api/projects` — create project
  - `GET /api/projects/:id` — get project with tasks
  - `PATCH /api/projects/:id` — update project
  - `DELETE /api/projects/:id` — archive project
- [ ] Link tasks to projects (tasks already have `project_id` FK)

### 4.2 Project Management UI
- [ ] Build `/projects` page — project list table (name, status, task count, completion %, last activity)
- [ ] Build `/projects/[id]` page — project detail with Kanban board
- [ ] Build Kanban board component — columns: Backlog / In Progress / Review / Done
- [ ] Task cards on Kanban: title, agent avatar, priority color, draggable between columns
- [ ] Drag-and-drop updates task status via `PATCH /api/tasks/:id`
- [ ] Project detail: linked threads section, activity log, project-level stats

### 4.3 KPI Dashboard
- [ ] API endpoint `GET /api/dashboard/kpis` — aggregate queries:
  - Total agent runs (last 30d)
  - Success rate %
  - Total tasks completed
  - Total cost ($)
  - Runs per day (grouped by agent)
  - Task completion rate over time
  - Cost per agent
  - Avg run duration by agent
- [ ] API endpoint `GET /api/dashboard/usage` — usage log aggregation
- [ ] Install Recharts
- [ ] Build `/dashboard` page layout — 3 rows: summary cards, charts, tables
- [ ] Build `KpiCard.tsx` — metric + trend indicator
- [ ] Build `RunsChart.tsx` — bar chart, runs per day colored by agent
- [ ] Build `TaskCompletionChart.tsx` — line chart over time
- [ ] Build `CostDonut.tsx` — donut chart, cost per agent
- [ ] Build `DurationChart.tsx` — bar chart, avg run duration by agent
- [ ] Build tables: top agents, most common tool calls, recent errors (linked to inspector), pending approvals

---

## Phase 5 — Integrations (Week 7-8)
**Goal: Agents can act on real external services with OAuth.**

### 5.1 Integration Framework
- [ ] Implement `BaseIntegration` class (`packages/integrations/base.py`) — `get_client()`, `refresh_token()`, token encryption/decryption (AES-256)
- [ ] API endpoints:
  - `GET /api/integrations` — list integrations + connection status for org
  - `GET /api/integrations/:provider/connect` — initiate OAuth flow (redirect to provider)
  - `GET /api/integrations/:provider/callback` — OAuth callback, store tokens
  - `DELETE /api/integrations/:provider` — disconnect (revoke + delete tokens)
- [ ] Build integration management UI (`/settings/integrations`) — list of available integrations, connected status, scopes, disconnect button

### 5.2 Google Integration (Gmail + Docs + Calendar)
- [ ] Implement Google OAuth flow (client ID/secret, scopes: gmail.send, gmail.readonly, docs, calendar.events)
- [ ] Build `GmailIntegration` — token refresh, client instantiation
- [ ] Implement tools for agents:
  - `gmail_search(query, max_results)`
  - `gmail_send(to, subject, body, thread_id?)` — **requires approval**
  - `gmail_get_thread(thread_id)`
- [ ] Build `GDocsIntegration`:
  - `gdocs_create(title, content)`
  - `gdocs_get(doc_id)`
  - `gdocs_update(doc_id, content)`
- [ ] Build `GCalIntegration`:
  - `gcal_create_event(title, datetime, attendees, description)` — **requires approval**
  - `gcal_list_events(date_range)`

### 5.3 YouTube Integration
- [ ] Implement YouTube OAuth flow (scopes: youtube.readonly, youtube.force-ssl)
- [ ] Build `YouTubeIntegration`:
  - `youtube_search(query, max_results)`
  - `youtube_get_analytics(channel_id, metrics, date_range)`
  - `youtube_get_video(video_id)`
  - `youtube_get_comments(video_id)`
  - `youtube_upload_video(...)` — **requires approval** (V2)
  - `youtube_update_video(...)` — **requires approval**
- [ ] Wire YouTube tools into Content Research agent

### 5.4 Slack Integration
- [ ] Implement Slack OAuth flow (scopes: chat:write, channels:read, users:read)
- [ ] Build `SlackIntegration`:
  - `slack_post_message(channel, text, blocks?)` — **requires approval unless whitelisted**
  - `slack_get_messages(channel, limit)`
  - `slack_create_channel(name)` — **requires approval**
- [ ] Wire Slack tools into agents

### 5.5 Integration Wiring
- [ ] Register all integration tools in the agent tool registry
- [ ] Agents check `integrations` table — gracefully degrade if required integration not connected
- [ ] Update agent config UI to show required/optional integrations per agent
- [ ] End-to-end test: Content Research agent → YouTube search → draft Google Doc → post summary to Slack → approval gate

---

## Phase 6 — Notifications + Polish (Week 9)
**Goal: Platform feels complete and production-ready.**

### 6.1 Notifications Backend
- [ ] API endpoints:
  - `GET /api/notifications` — list notifications for user (paginated)
  - `PATCH /api/notifications/:id/read` — mark as read
  - `PATCH /api/notifications/read-all` — mark all as read
- [ ] Create notifications on events: task_complete, approval_needed, agent_error, agent_mention
- [ ] Email notifications via Resend:
  - Approval needed → immediate
  - Task completed → configurable digest (immediate / hourly / daily)
  - Agent error → immediate
  - Weekly summary → Monday 8am (APScheduler)

### 6.2 Notifications UI
- [ ] Build `NotificationCenter.tsx` — bell icon in TopBar, badge with unread count, dropdown with last 20 notifications
- [ ] Each notification: icon by type, title, body, timestamp, click to navigate (action_url)
- [ ] Real-time: subscribe to `notifications` INSERT via Supabase Realtime
- [ ] Build `/settings/notifications` page — per-type preferences (in-app only / email + in-app / none)

### 6.3 Org Settings & Team Management
- [ ] Build `/settings/team` page — list org members, roles (owner/admin/member/viewer)
- [ ] Invite flow: owner enters email → API sends invite via Resend → recipient signs up and joins org
- [ ] Role management: change member roles, remove members
- [ ] Org settings: name, slug, plan display

### 6.4 Polish & Error Handling
- [ ] Add loading skeletons for all list pages (threads, tasks, runs, projects, agents)
- [ ] Add empty states for all list pages (no tasks yet, no runs yet, etc.)
- [ ] Global error boundary with friendly error page
- [ ] Toast notifications for success/error actions (task created, approval submitted, etc.)
- [ ] Retry button on failed agent runs (re-triggers from last checkpoint)
- [ ] Mobile responsive: sidebar collapses to hamburger menu, chat is full-width
- [ ] Review and tighten RLS policies — test cross-org data isolation
- [ ] Rate limiting middleware (`middleware/ratelimit.py`) — per-org, per-endpoint
- [ ] End-to-end happy path tests: signup → create thread → chat with agent → tool calls → approval → task completes → check dashboard

---

## Post-MVP Backlog (V2)
- [ ] Content Manager Agent (full YouTube pipeline: research → script → thumbnail → publish)
- [ ] Monday.com integration
- [ ] Dropbox integration
- [ ] Scheduled recurring tasks (cron-style via APScheduler)
- [ ] Approval workflows with roles (editor can approve, admin can override)
- [ ] Custom agent registration UI (upload LangGraph graph via UI)
- [ ] Public agent marketplace
- [ ] White-label for agency clients
- [ ] Mobile app
- [ ] Agent memory (RAG with pgvector embeddings)
- [ ] Voice input in chat
- [ ] File attachments in chat (images, PDFs, CSVs)
- [ ] Observability: Sentry, PostHog, Langfuse
