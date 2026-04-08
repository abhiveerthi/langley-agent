# AgentOS — Product Requirements Document

**Version:** 1.0  
**Status:** MVP Spec  
**Target:** Solo SWE / AI Agency — multi-tenant agentic platform for creators and SMBs  

---

## Table of Contents

1. [Vision & Problem Statement](#1-vision--problem-statement)
2. [Target Users](#2-target-users)
3. [Product Principles](#3-product-principles)
4. [MVP Scope](#4-mvp-scope)
5. [Monorepo Architecture](#5-monorepo-architecture)
6. [Tech Stack](#6-tech-stack)
7. [Data Models](#7-data-models)
8. [Feature Specs](#8-feature-specs)
   - 8.1 [Auth & Multi-tenancy](#81-auth--multi-tenancy)
   - 8.2 [Chat Interface](#82-chat-interface)
   - 8.3 [Agent Management](#83-agent-management)
   - 8.4 [Task Management](#84-task-management)
   - 8.5 [Project Management](#85-project-management)
   - 8.6 [Pipeline Inspector (Human-in-the-Loop)](#86-pipeline-inspector-human-in-the-loop)
   - 8.7 [KPI Dashboard](#87-kpi-dashboard)
   - 8.8 [Notifications](#88-notifications)
   - 8.9 [Integrations](#89-integrations)
9. [LangGraph Integration Layer](#9-langgraph-integration-layer)
10. [Custom Agent Extension System](#10-custom-agent-extension-system)
11. [Content Manager Agent (Future Module)](#11-content-manager-agent-future-module)
12. [API Design](#12-api-design)
13. [Real-Time Architecture](#13-real-time-architecture)
14. [Security & Compliance](#14-security--compliance)
15. [MVP Build Order](#15-mvp-build-order)
16. [Folder Structure (Full)](#16-folder-structure-full)
17. [Environment Variables](#17-environment-variables)
18. [Deployment](#18-deployment)
19. [Scale Considerations](#19-scale-considerations)

---

## 1. Vision & Problem Statement

**Vision:** A VSCode Copilot for YouTubers and creator-economy businesses — a single agentic workspace where AI agents handle the operational layer of running a channel: research, scripting, scheduling, thumbnail generation, clip creation, publishing, and analytics.

**Problem:** Creators and small creator-economy agencies manage 6–10 different tools (Notion, Monday, email, YouTube Studio, Canva, Google Docs, Slack) with no intelligence connecting them. Every workflow is manual. Every status check is a context switch. There is no system that knows the full context of their operation and can act on their behalf.

**Solution:** AgentOS is a chat-first, agentic workspace. Clients talk to agents in natural language. Agents plan, execute, schedule, and report back. Everything is transparent — every tool call, every decision, every result is visible and auditable. Humans stay in the loop on consequential actions. The system is extensible — new agents can be added as the client's needs grow.

---

## 2. Target Users

**Primary — YouTube creators / creator studios (MVP)**
- Solo YouTubers with 10k–500k subscribers
- Small creator agencies managing 3–10 channels
- Pain: content pipeline is entirely manual, slow, and inconsistent

**Persona — Alex, solo YouTuber (personal finance, 85k subs)**
- Posts 2x/week
- Spends 4–6 hours per video on research + scripting
- Has a VA but coordination is chaotic
- Would pay $150–300/month for a system that cuts that to 1 hour

---

## 3. Product Principles

1. **Chat first.** Every feature is reachable from the chat interface. The sidebar is navigation, not the product.
2. **Transparent agents.** Every tool call, every decision, every error is visible. No black boxes.
3. **Humans approve consequences.** Any action that changes the external world (sends email, publishes content, moves money) requires explicit approval unless the client has whitelisted it.
4. **Config over code for clients.** New agents are dropped in as config files. Clients don't see code.
5. **SWE-friendly extension.** The underlying architecture is code-native. Adding a new LangGraph agent is dropping a Python file and registering it.
6. **Multi-tenant from day one.** Every table is scoped by `org_id`. No data leakage between clients.

---

## 4. MVP Scope

### In MVP
- Chat interface with streaming + tool call visualization
- 2 built-in agents: General Assistant, Content Research Agent
- Task management (create, assign to agent, track status)
- Project management (group tasks into projects)
- Pipeline inspector (see agent steps, tool calls, errors, human-in-the-loop)
- Basic KPI dashboard (tasks completed, agent runs, token usage, cost)
- Notifications (in-app + email)
- Integrations: Google (Gmail, YouTube, Docs), Slack
- Auth + multi-tenancy (orgs + members)
- Custom agent registration (drop in a LangGraph graph, it appears in the UI)

### Post-MVP (V2)
- Content Manager Agent (clips, thumbnails, full pipeline)
- Monday.com, Dropbox integrations
- Scheduled recurring tasks (cron-style)
- Approval workflows with roles (editor can approve, admin can override)
- Public agent marketplace
- White-label for agency clients
- Mobile app

---

## 5. Monorepo Architecture

```
agentos/
├── apps/
│   ├── web/                    # Next.js frontend app
│   │   └── components/         # React component library
│   └── api/                    # FastAPI + LangGraph backend
│       ├── agents/             # LangGraph agent definitions
│       ├── integrations/       # Third-party API clients (Google, Slack, YouTube, etc.)
│       ├── db/                 # Database client + queries
│       └── routes/             # API endpoints
├── packages/
│   └── core/                   # Shared types & schemas (TS + Python)
│       ├── schemas/            # Zod (TS) + Pydantic (Python) — single source of truth
│       └── constants/          # Shared constants
├── infra/
│   ├── docker-compose.yml      # Local dev stack
│   └── supabase/               # Supabase config + migrations
├── scripts/
│   └── deploy.sh
├── .env.example
└── package.json                # Root workspace
```

**Monorepo tooling:** pnpm workspaces for JS packages (Next.js, shared types), Poetry for Python packages (FastAPI backend). Shared types in `packages/core` are generated from a single source of truth: Zod schemas (TS side) sync with Pydantic models (Python side) to keep frontend-backend contracts in sync.

---

## 6. Tech Stack

### Frontend (`apps/web`)
| Layer | Choice | Reason |
|---|---|---|
| Framework | Next.js 16 App Router | SSR, SSE streaming, server actions, edge runtime |
| UI | shadcn/ui + Tailwind | Fast, unstyled primitives, design system ready |
| Real-time | Supabase Realtime + SSE | Live updates without polling |
| Auth | Supabase Auth | Built-in, handles OAuth for Google/Slack |
| Charts | Recharts | KPI dashboard |

### Backend (`apps/api`)
| Layer | Choice | Reason |
|---|---|---|
| Framework | FastAPI | Async Python, OpenAPI out of the box |
| Agent orchestration | LangGraph | Stateful multi-agent workflows with built-in step tracking |
| LLM | Anthropic Claude (Haiku + Sonnet) | Cost control per task complexity |
| Background tasks | LangGraph (agents) + FastAPI background tasks | Stateful workflows via LangGraph; simple ops via FastAPI tasks |
| Real-time streaming | FastAPI SSE | Streams agent step updates to frontend as they happen |
| Cron | APScheduler | Scheduled recurring tasks |
| DB | Supabase (Postgres) | Single DB, RLS, realtime |
| Storage | Supabase Storage | Files, thumbnails, exports |
| Search | pgvector (via Supabase) | RAG for agent memory |

> **Task visibility:** Each LangGraph workflow emits step-level state (pending, running, complete, failed) streamed via SSE to the frontend. The UI displays a human-readable task feed — similar to GitHub Copilot Agents — showing what is running, each step's status, and a plain-language summary of what the agent did. Task history is persisted in Postgres.

### Infrastructure
| Layer | Choice |
|---|---|
| Frontend hosting | Vercel |
| API hosting | Render (Docker) |
| Database | Supabase |
| Email | Resend |
| File storage | Supabase Storage |

---

## 7. Data Models

### Core Tables (`packages/db/migrations/001_core.sql`)

```sql
-- Organizations (one per client / workspace)
create table orgs (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  slug text unique not null,
  plan text default 'starter',         -- starter | growth | pro
  settings jsonb default '{}',
  created_at timestamptz default now()
);

-- Users (members of orgs)
create table users (
  id uuid primary key references auth.users(id),
  email text unique not null,
  full_name text,
  avatar_url text,
  created_at timestamptz default now()
);

-- Org memberships
create table org_members (
  id uuid primary key default gen_random_uuid(),
  org_id uuid references orgs(id) on delete cascade,
  user_id uuid references users(id) on delete cascade,
  role text default 'member',          -- owner | admin | member | viewer
  created_at timestamptz default now(),
  unique(org_id, user_id)
);

-- Agents registered in the system
create table agents (
  id uuid primary key default gen_random_uuid(),
  org_id uuid references orgs(id) on delete cascade,
  name text not null,
  slug text not null,                  -- matches packages/agents/<slug>
  description text,
  icon text,
  capabilities jsonb default '[]',     -- list of capability tags
  tools jsonb default '[]',            -- list of tool names this agent can use
  config jsonb default '{}',           -- agent-specific config
  is_system boolean default false,     -- system agents vs custom
  active boolean default true,
  created_at timestamptz default now(),
  unique(org_id, slug)
);

-- Chat threads
create table threads (
  id uuid primary key default gen_random_uuid(),
  org_id uuid references orgs(id) on delete cascade,
  user_id uuid references users(id),
  agent_id uuid references agents(id),
  project_id uuid references projects(id),
  title text,
  status text default 'active',        -- active | archived
  metadata jsonb default '{}',
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

-- Messages in threads
create table messages (
  id uuid primary key default gen_random_uuid(),
  thread_id uuid references threads(id) on delete cascade,
  role text not null,                  -- user | assistant | tool | system
  content text,
  tool_calls jsonb,                    -- array of tool call objects
  tool_results jsonb,                  -- array of tool result objects
  metadata jsonb default '{}',         -- tokens, model, latency, cost
  created_at timestamptz default now()
);

-- Agent run records (one per graph invocation)
create table agent_runs (
  id uuid primary key default gen_random_uuid(),
  org_id uuid references orgs(id) on delete cascade,
  thread_id uuid references threads(id),
  task_id uuid references tasks(id),
  agent_id uuid references agents(id),
  status text default 'running',       -- running | completed | failed | paused | cancelled
  input jsonb,
  output jsonb,
  error text,
  steps jsonb default '[]',            -- array of step objects (node name, input, output, duration)
  tool_calls jsonb default '[]',       -- flat list of all tool calls for inspector
  input_tokens int default 0,
  output_tokens int default 0,
  cost_usd numeric(10,6) default 0,
  started_at timestamptz default now(),
  completed_at timestamptz,
  metadata jsonb default '{}'
);

-- Projects
create table projects (
  id uuid primary key default gen_random_uuid(),
  org_id uuid references orgs(id) on delete cascade,
  name text not null,
  description text,
  status text default 'active',        -- active | completed | archived
  color text default '#6366F1',
  icon text,
  metadata jsonb default '{}',
  created_at timestamptz default now()
);

-- Tasks
create table tasks (
  id uuid primary key default gen_random_uuid(),
  org_id uuid references orgs(id) on delete cascade,
  project_id uuid references projects(id),
  thread_id uuid references threads(id),
  agent_id uuid references agents(id),
  created_by uuid references users(id),
  title text not null,
  description text,
  status text default 'pending',       -- pending | running | paused | completed | failed | cancelled
  priority text default 'medium',      -- low | medium | high | urgent
  type text default 'manual',          -- manual | agent | scheduled | recurring
  input jsonb default '{}',            -- input passed to agent when run
  output jsonb,                        -- result from agent
  scheduled_at timestamptz,            -- for scheduled tasks
  cron_expression text,                -- for recurring tasks
  due_at timestamptz,
  completed_at timestamptz,
  requires_approval boolean default false,
  approved_by uuid references users(id),
  approved_at timestamptz,
  metadata jsonb default '{}',
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

-- Human-in-the-loop approval requests
create table approvals (
  id uuid primary key default gen_random_uuid(),
  org_id uuid references orgs(id) on delete cascade,
  run_id uuid references agent_runs(id),
  task_id uuid references tasks(id),
  thread_id uuid references threads(id),
  requested_by_agent text,             -- agent slug
  action_type text not null,           -- send_email | publish_post | create_event | etc
  action_payload jsonb not null,       -- the full action to be executed on approval
  preview text,                        -- human-readable description of what will happen
  status text default 'pending',       -- pending | approved | rejected | expired
  reviewed_by uuid references users(id),
  reviewed_at timestamptz,
  expires_at timestamptz,
  created_at timestamptz default now()
);

-- Notifications
create table notifications (
  id uuid primary key default gen_random_uuid(),
  org_id uuid references orgs(id) on delete cascade,
  user_id uuid references users(id),
  type text not null,                  -- task_complete | approval_needed | agent_error | mention
  title text not null,
  body text,
  action_url text,
  read boolean default false,
  metadata jsonb default '{}',
  created_at timestamptz default now()
);

-- Integration connections (OAuth tokens per org)
create table integrations (
  id uuid primary key default gen_random_uuid(),
  org_id uuid references orgs(id) on delete cascade,
  provider text not null,             -- google | slack | monday | dropbox | youtube
  status text default 'active',       -- active | expired | revoked
  access_token text,                  -- encrypted
  refresh_token text,                 -- encrypted
  token_expires_at timestamptz,
  scopes jsonb default '[]',
  metadata jsonb default '{}',        -- provider-specific data (channel IDs, etc)
  created_at timestamptz default now(),
  unique(org_id, provider)
);

-- Usage log for billing / cost tracking
create table usage_log (
  id uuid primary key default gen_random_uuid(),
  org_id uuid references orgs(id) on delete cascade,
  agent_id uuid references agents(id),
  run_id uuid references agent_runs(id),
  model text not null,
  input_tokens int default 0,
  output_tokens int default 0,
  cost_usd numeric(10,6) default 0,
  created_at timestamptz default now()
);

-- Agent memory (vector embeddings for RAG)
create table agent_memory (
  id uuid primary key default gen_random_uuid(),
  org_id uuid references orgs(id) on delete cascade,
  agent_id uuid references agents(id),
  thread_id uuid references threads(id),
  content text not null,
  embedding vector(1536),
  metadata jsonb default '{}',
  created_at timestamptz default now()
);

-- Indexes
create index on threads(org_id, created_at desc);
create index on messages(thread_id, created_at);
create index on agent_runs(org_id, status, created_at desc);
create index on tasks(org_id, status, created_at desc);
create index on approvals(org_id, status, created_at desc);
create index on notifications(user_id, read, created_at desc);
create index on usage_log(org_id, created_at);
create index on agent_memory using ivfflat (embedding vector_cosine_ops);

-- Row Level Security
alter table orgs enable row level security;
alter table threads enable row level security;
alter table messages enable row level security;
alter table tasks enable row level security;
alter table approvals enable row level security;
alter table notifications enable row level security;

-- RLS Policies (example for threads)
create policy "members can read own org threads"
  on threads for select
  using (org_id in (
    select org_id from org_members where user_id = auth.uid()
  ));
```

---

## 8. Feature Specs

### 8.1 Auth & Multi-tenancy

**Behavior:**
- Sign up creates a user and a personal org
- Invite flow: owner sends email invite, recipient signs up and joins org
- OAuth login via Google (required for Google integrations)
- JWT stored in httpOnly cookie, refreshed automatically
- Every API request includes `org_id` derived from the JWT claim
- RLS enforces data isolation at the DB layer — no application-layer mistakes can leak data

**Routes:**
- `/auth/login` — email + password or Google OAuth
- `/auth/signup` — create account + org
- `/auth/invite/[token]` — accept org invite
- `/settings/team` — manage members and roles

---

### 8.2 Chat Interface

**The core product surface.** Modeled after Claude/ChatGPT but with first-class agentic UI.

**Layout:**
```
┌─────────────────────────────────────────────────────────┐
│ Sidebar          │ Chat window                           │
│                  │                                       │
│ [+ New Chat]     │ ┌─ Thread header ──────────────────┐  │
│                  │ │ Agent: Content Research  [config] │  │
│ Recent threads   │ └──────────────────────────────────┘  │
│ > How to script  │                                       │
│ > VA loan follow │ [messages + tool call cards]          │
│ > Market report  │                                       │
│                  │ ┌─ Input ──────────────────────────┐  │
│ Projects ──────  │ │ @ agent  /command  [attach]  [▶] │  │
│ > Channel Q2     │ └──────────────────────────────────┘  │
│ > Lead Pipeline  │                                       │
│                  │                                       │
│ Tasks ─────────  │                                       │
│ > 3 pending      │                                       │
│ > 1 needs review │                                       │
└─────────────────────────────────────────────────────────┘
```

**Message types rendered in the chat:**

1. **User message** — plain text bubble
2. **Assistant message** — streaming markdown with syntax highlighting
3. **Tool call card** — collapsible card showing:
   - Tool name + icon
   - Status badge: running / success / error
   - Input params (collapsed by default)
   - Output / result (collapsed by default)
   - Duration and cost
4. **Approval request card** — prominent card with:
   - "Waiting for your approval" header
   - Human-readable description of the action
   - Preview of what will be sent/created/modified
   - Approve / Reject buttons (fires API immediately)
5. **Agent thinking** — animated typing indicator with node name ("Researching YouTube trends...")
6. **Error card** — red border, error message, retry button
7. **Task created card** — when agent creates a task, shows task card inline

**Input features:**
- `@agent-name` to switch active agent mid-conversation
- `/commands` for quick actions (`/new-task`, `/schedule`, `/summarize`)
- File attachment (images, PDFs, CSVs passed to agent context)
- Voice input (V2)

**Streaming:**
- Messages stream token by token via SSE
- Tool call cards appear as tools are invoked, update in place as results arrive
- No full page re-render — only the new content appends

---

### 8.3 Agent Management

**Agent registry:** Every agent available to an org is listed here. System agents ship with the platform. Custom agents are registered by the workspace owner.

**Agent card shows:**
- Name, icon, description
- Capability tags (research, writing, scheduling, publishing, etc.)
- Tools it can use
- Last active / run count / success rate
- Enable / disable toggle per org
- Config panel (model override, temperature, custom instructions, tool allowlist)

**Custom agent registration:**
- Owner uploads or pastes a LangGraph graph definition
- System validates the graph schema
- Sets required integrations
- Agent appears in the agent selector

**Routes:**
- `/agents` — agent gallery
- `/agents/[slug]` — agent detail + config
- `/agents/new` — register custom agent (developer mode)

---

### 8.4 Task Management

Tasks are the atomic unit of agentic work. Every agent run is tied to a task. Tasks can be created by users (manually) or by agents (autonomously).

**Task states:**
```
pending → running → paused (awaiting approval) → completed
                  ↘ failed
                  ↘ cancelled
```

**Task list view:**
- Filter by: status, agent, project, priority, date range
- Sort by: created, due date, priority, status
- Bulk actions: cancel, reassign, export
- Quick inline status update

**Task detail view:**
- Title, description, assigned agent
- Input / output (collapsible JSON)
- Run history (every time this task was attempted)
- Linked thread (click to open chat context)
- Approval history if applicable
- Timeline of state changes

**Creating tasks:**
- From chat: agent creates a task automatically when it starts work
- Manually: user creates task, assigns to agent, sets priority and due date
- From template: pre-defined task templates per agent type

---

### 8.5 Project Management

Projects group related tasks and threads. For a YouTuber, a project is a video. For a real estate firm, a project is a listing.

**Project board view:**
- Kanban columns: Backlog / In Progress / Review / Done
- Each card is a task, draggable between columns
- Agent avatar shows which agent owns each card
- Color-coded by priority

**Project list view:**
- Table with project name, status, task count, completion %, last activity

**Project detail:**
- Task board
- Linked threads
- Files / attachments (Supabase Storage)
- Activity log (all state changes across tasks)
- Project-level KPIs (tasks completed, time to completion, agent runs)

---

### 8.6 Pipeline Inspector (Human-in-the-Loop)

The killer feature for trust and debugging. Every agent run is fully observable.

**Run list:**
- Real-time list of all agent runs across the org
- Status badges with live updates via Supabase Realtime
- Filter by agent, status, date, cost

**Run detail — the inspector:**

```
Run #a3f9b2 — Content Research Agent
Status: completed  Duration: 47s  Cost: $0.024  Tokens: 8,420

Timeline ─────────────────────────────────────────────────

  ● [00:00] START
    Input: { "topic": "how to invest at 25", "niche": "personal finance" }

  ● [00:01] Node: router
    Output: { "intent": "research", "route": "web_search" }

  ● [00:02] Tool call: web_search                          [expand ▾]
    Input:  { "query": "how to invest at 25 YouTube 2026" }
    Output: [ 8 results... ]
    Duration: 1.2s

  ● [00:04] Tool call: youtube_search                      [expand ▾]
    Input:  { "query": "invest at 25", "max_results": 10 }
    Output: [ top videos, view counts, engagement rates... ]
    Duration: 2.1s

  ● [00:08] Node: synthesize_research
    (thinking...) Analyzing search results...
    Output: { "key_angles": [...], "competitor_gaps": [...] }

  ● [00:12] Node: generate_outline
    Output: { "outline": "Hook → 5 sections → CTA" }

  ● [00:15] APPROVAL REQUESTED                          ← paused here
    Action: send_draft_to_slack
    Preview: "Send draft outline to #content channel"
    → Approved by: Alex (00:18)

  ● [00:18] Tool call: slack_post_message               [expand ▾]
    Input:  { "channel": "#content", "text": "..." }
    Output: { "ok": true, "ts": "1234567890.123" }

  ● [00:19] END
    Output: { "research": "...", "outline": "...", "status": "complete" }
```

**Features:**
- Expand/collapse each step
- Raw JSON view for any input/output
- Error details with stack trace for failed steps
- Re-run from any checkpoint (LangGraph thread resume)
- Cost breakdown per node
- Token usage per LLM call
- "Resume" button for paused runs
- "Cancel" button for running runs
- Export run as JSON for debugging

---

### 8.7 KPI Dashboard

**Org-level metrics:**

Row 1 — Summary cards (last 30 days):
- Total agent runs
- Success rate %
- Total tasks completed
- Total cost ($)

Row 2 — Charts:
- Agent runs per day (bar chart, colored by agent)
- Task completion rate over time (line chart)
- Cost per agent (donut chart)
- Average run duration by agent (bar chart)

Row 3 — Tables:
- Top agents by run count
- Most common tool calls
- Recent errors (with link to run inspector)
- Pending approvals

**Per-agent metrics (on agent detail page):**
- Run count, success rate, avg duration, avg cost
- Most used tools
- Error frequency and types
- Performance over time

---

### 8.8 Notifications

**In-app notification center:**
- Bell icon in nav, badge with unread count
- Dropdown shows last 20 notifications
- Types: task complete, approval needed, agent error, agent mention, scheduled task about to run

**Email notifications (via Resend):**
- Approval needed: immediate
- Task completed: digest (configurable: immediate / hourly / daily)
- Agent error: immediate
- Weekly summary: Monday 8am

**Notification preferences:**
- Per user, per notification type
- Per-channel override (in-app only, email + in-app, none)

**Real-time:**
- Notifications pushed via Supabase Realtime
- No polling — instant delivery on the same tab or other open tabs

---

### 8.9 Integrations

Each integration is an OAuth connection stored in the `integrations` table with encrypted tokens. All integrations are optional — agents degrade gracefully if a required integration isn't connected.

**Integration management UI:**
- `/settings/integrations` — list of all available integrations
- Each shows: connected status, connected account, scopes, last used, disconnect button
- Connect flow: OAuth popup → token stored → scopes validated → integration active

#### Google (Gmail + Docs + Calendar)
- OAuth 2.0 with `gmail.readonly`, `gmail.send`, `docs.readonly`, `docs`, `calendar.events` scopes
- Tools exposed to agents:
  - `gmail_search(query, max_results)` — search inbox
  - `gmail_send(to, subject, body, thread_id?)` — send email
  - `gmail_get_thread(thread_id)` — get full email thread
  - `gdocs_create(title, content)` — create a Google Doc
  - `gdocs_get(doc_id)` — read a Doc
  - `gdocs_update(doc_id, content)` — update a Doc
  - `gcal_create_event(title, datetime, attendees, description)` — create calendar event
  - `gcal_list_events(date_range)` — list upcoming events

#### YouTube Data API
- OAuth 2.0 with `youtube.readonly`, `youtube.upload`, `youtube.force-ssl` scopes
- Tools exposed to agents:
  - `youtube_search(query, max_results)` — search YouTube
  - `youtube_get_analytics(channel_id, metrics, date_range)` — pull channel analytics
  - `youtube_get_video(video_id)` — get video metadata + stats
  - `youtube_upload_video(file_path, title, description, tags)` — upload video (approval required)
  - `youtube_update_video(video_id, title, description, thumbnail)` — update metadata
  - `youtube_get_comments(video_id)` — get recent comments

#### Slack
- OAuth with `chat:write`, `channels:read`, `users:read` scopes
- Tools exposed:
  - `slack_post_message(channel, text, blocks?)` — post message (approval required unless whitelisted)
  - `slack_get_messages(channel, limit)` — read recent messages
  - `slack_create_channel(name)` — create a channel (approval required)

#### Monday.com (V2)
- API key auth
- Tools: create item, update status, get board items, create update

#### Dropbox (V2)
- OAuth 2.0
- Tools: upload file, get file, list folder, share link

**Integration architecture:**

```python
# packages/integrations/base.py
class BaseIntegration:
    provider: str
    required_scopes: list[str]

    async def get_client(self, org_id: str) -> Any:
        """Load integration tokens from DB, refresh if expired, return client."""
        integration = await db.integrations.get(org_id, self.provider)
        if integration.token_expires_at < now():
            integration = await self.refresh_token(integration)
        return self.build_client(integration.access_token)

    async def refresh_token(self, integration) -> Integration:
        """Provider-specific token refresh logic."""
        raise NotImplementedError

# packages/integrations/google/gmail.py
class GmailIntegration(BaseIntegration):
    provider = "google"
    required_scopes = ["gmail.send", "gmail.readonly"]

    async def send_email(self, org_id: str, to: str, subject: str, body: str):
        client = await self.get_client(org_id)
        # ... gmail API call
```

Each integration exposes a set of LangChain/LangGraph tools that wrap its API methods. Tools are imported into agents by capability.

---

## 9. LangGraph Integration Layer

### Agent Base Class

```python
# packages/agents/core/base.py
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.postgres import PostgresSaver
from typing import TypedDict, Any
import os

class BaseAgentState(TypedDict):
    messages: list[dict]
    org_id: str
    user_id: str
    thread_id: str
    task_id: str | None
    metadata: dict[str, Any]

class BaseAgent:
    slug: str
    name: str
    description: str
    tools: list          # LangChain tools
    model: str = "claude-haiku-4-5-20251001"

    def __init__(self):
        self.checkpointer = PostgresSaver.from_conn_string(
            os.environ["DATABASE_URL"]
        )
        self.graph = self.build_graph()
        self.app = self.graph.compile(
            checkpointer=self.checkpointer,
            interrupt_before=self.interrupt_before_nodes
        )

    @property
    def interrupt_before_nodes(self) -> list[str]:
        """Override to specify nodes that require human approval."""
        return []

    def build_graph(self) -> StateGraph:
        """Override to define the agent's graph."""
        raise NotImplementedError

    async def run(self, input: dict, thread_id: str, stream: bool = False):
        config = {"configurable": {"thread_id": thread_id}}
        if stream:
            return self.app.astream_events(input, config=config, version="v2")
        return await self.app.ainvoke(input, config=config)

    async def resume(self, thread_id: str, approved: bool, payload: dict = None):
        """Resume a paused graph after human approval."""
        config = {"configurable": {"thread_id": thread_id}}
        if not approved:
            # Inject rejection into state and continue
            await self.app.aupdate_state(
                config,
                {"approval_result": "rejected", "approval_payload": payload}
            )
        return await self.app.ainvoke(None, config=config)

    async def get_state(self, thread_id: str):
        config = {"configurable": {"thread_id": thread_id}}
        return await self.app.aget_state(config)
```

### Run Tracking Middleware

Every agent run is automatically logged to `agent_runs` via a middleware wrapper that intercepts LangGraph stream events and writes them to Supabase. No manual logging in agent code.

```python
# packages/agents/core/tracker.py
class RunTracker:
    """Wraps an agent run and persists all events to agent_runs table."""

    async def track(self, agent: BaseAgent, input: dict, thread_id: str, run_id: str):
        steps = []
        tool_calls = []
        input_tokens = 0
        output_tokens = 0

        try:
            async for event in agent.run(input, thread_id, stream=True):
                event_type = event["event"]

                if event_type == "on_chain_start":
                    steps.append({
                        "node": event["name"],
                        "started_at": now_iso(),
                        "input": event.get("data", {}).get("input")
                    })

                elif event_type == "on_chain_end":
                    # Update last step with output and duration
                    step = find_step(steps, event["name"])
                    step["output"] = event["data"].get("output")
                    step["completed_at"] = now_iso()

                elif event_type == "on_tool_start":
                    tool_calls.append({
                        "tool": event["name"],
                        "input": event["data"].get("input"),
                        "started_at": now_iso()
                    })

                elif event_type == "on_tool_end":
                    tc = find_tool_call(tool_calls, event["name"])
                    tc["output"] = event["data"].get("output")
                    tc["completed_at"] = now_iso()

                elif event_type == "on_chat_model_end":
                    usage = event["data"]["output"].usage_metadata
                    input_tokens += usage.input_tokens
                    output_tokens += usage.output_tokens

                # Stream event to SSE for UI
                await self.stream_to_client(run_id, event)

                # Persist incrementally
                await db.agent_runs.update(run_id, {
                    "steps": steps,
                    "tool_calls": tool_calls,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cost_usd": calculate_cost(input_tokens, output_tokens, agent.model)
                })

        except Exception as e:
            await db.agent_runs.update(run_id, {
                "status": "failed",
                "error": str(e),
                "completed_at": now_iso()
            })
            raise
```

### Agent Registry

```python
# packages/agents/registry.py
from agents.general import GeneralAgent
from agents.content_research import ContentResearchAgent

AGENT_REGISTRY: dict[str, type[BaseAgent]] = {
    "general": GeneralAgent,
    "content-research": ContentResearchAgent,
}

def get_agent(slug: str) -> BaseAgent:
    if slug not in AGENT_REGISTRY:
        raise ValueError(f"Unknown agent: {slug}")
    return AGENT_REGISTRY[slug]()

def register_agent(slug: str, agent_class: type[BaseAgent]):
    """Called at startup to register custom agents loaded from DB."""
    AGENT_REGISTRY[slug] = agent_class
```

---

## 10. Custom Agent Extension System

This is what makes the platform extensible. A developer (you, or a client's dev) can add a new LangGraph agent without touching the core platform.

### Agent Manifest File

Every custom agent ships with a `manifest.json`:

```json
{
  "slug": "content-manager",
  "name": "Content Manager",
  "description": "Full YouTube content pipeline — research, script, thumbnail, publish",
  "version": "1.0.0",
  "icon": "video",
  "capabilities": ["research", "writing", "image-generation", "publishing"],
  "required_integrations": ["youtube", "google"],
  "optional_integrations": ["slack"],
  "tools": [
    "youtube_search",
    "youtube_upload_video",
    "gdocs_create",
    "slack_post_message"
  ],
  "interrupt_before": [
    "publish_video",
    "send_notification"
  ],
  "config_schema": {
    "channel_id": { "type": "string", "required": true, "label": "YouTube Channel ID" },
    "default_language": { "type": "string", "default": "en", "label": "Default Language" },
    "auto_publish": { "type": "boolean", "default": false, "label": "Auto-publish (no approval)" }
  }
}
```

### Adding a New Agent (Developer Workflow)

```bash
# 1. Scaffold the agent
pnpm run add-agent content-manager

# Creates:
# packages/agents/content-manager/
#   __init__.py
#   agent.py          ← LangGraph graph definition
#   tools.py          ← agent-specific tools
#   manifest.json     ← metadata
#   prompts.py        ← system prompts

# 2. Define the graph in agent.py (LangGraph code)
# 3. Register manifest in the UI by calling the API
POST /api/agents/register
{ "manifest": {...}, "org_id": "..." }

# 4. Agent appears in the agent gallery
# 5. Org enables it, configures it, uses it
```

### Dynamic Graph Loading

For truly custom agents where a client's developer writes the LangGraph code, the platform can load graphs dynamically at runtime. This is the "plugin" model — the graph is uploaded as a Python module, sandboxed, and instantiated on demand.

This is a V2 feature. For MVP, all agents are bundled with the platform and deployed together.

---

## 11. Content Manager Agent (Future Module)

Defined here as a spec so the architecture is designed to support it.

### What It Does

Given a video topic and channel config, this agent autonomously:
1. Researches the topic (YouTube search, web search, competitor analysis)
2. Generates an outline + full script
3. Creates thumbnail concepts (text + layout descriptions for DALL-E / Midjourney)
4. Generates B-roll search queries
5. Creates a short-form clip script (for YouTube Shorts / TikTok)
6. Writes the video description + SEO tags
7. Packages everything into a Google Doc
8. Posts summary to Slack for review
9. On approval, schedules the upload

### Graph Nodes

```
topic_input
  → research_parallel [web_search, youtube_search, trend_analysis]
  → competitor_gap_analysis
  → outline_generation
  → script_writing
  → review_loop [review → revise → review, max 3x]
  → thumbnail_concepts [parallel with clip_script]
  → seo_generation [parallel]
  → package_to_gdoc
  → APPROVAL: post_to_slack_for_review
  → APPROVAL: schedule_youtube_upload
  → END
```

### Clip Generation (V2+)

Integration with video processing APIs (Shotstack, Creatomate, or custom FFmpeg workers) to:
- Extract highlight clips from uploaded raw footage
- Overlay captions (via Whisper transcription)
- Apply brand template
- Export in platform-specific formats (YouTube Shorts 9:16, TikTok, Instagram Reels)

This requires a video worker service (`apps/workers/video_processor.py`) that runs as a separate Celery worker on GPU-capable infrastructure.

---

## 12. API Design

### FastAPI App Structure (`apps/api`)

```
apps/api/
├── main.py                  # App entry, middleware, CORS
├── routers/
│   ├── chat.py              # SSE streaming chat endpoint
│   ├── agents.py            # Agent CRUD + registration
│   ├── tasks.py             # Task management
│   ├── projects.py          # Project management
│   ├── runs.py              # Agent run inspector
│   ├── approvals.py         # Human-in-the-loop actions
│   ├── integrations.py      # OAuth flows + token management
│   ├── notifications.py     # Notification management
│   └── dashboard.py         # KPI aggregation queries
├── middleware/
│   ├── auth.py              # JWT validation + org context
│   └── ratelimit.py         # Per-org rate limiting
├── dependencies.py          # FastAPI dependencies (db, auth, etc.)
└── worker.py                # Celery worker entry
```

### Key Endpoints

```
POST   /api/chat/stream              # Start/continue a chat, returns SSE stream
POST   /api/chat/threads             # Create a new thread
GET    /api/chat/threads             # List threads for org
GET    /api/chat/threads/:id         # Get thread with messages
DELETE /api/chat/threads/:id         # Archive thread

GET    /api/agents                   # List agents for org
POST   /api/agents/register          # Register custom agent
PATCH  /api/agents/:slug/config      # Update agent config
PATCH  /api/agents/:slug/toggle      # Enable/disable agent

GET    /api/tasks                    # List tasks (filterable)
POST   /api/tasks                    # Create task
PATCH  /api/tasks/:id                # Update task
POST   /api/tasks/:id/run            # Trigger agent run for task
POST   /api/tasks/:id/cancel         # Cancel running task

GET    /api/runs                     # List agent runs (filterable)
GET    /api/runs/:id                 # Get run detail with full timeline
POST   /api/runs/:id/resume          # Resume paused run
POST   /api/runs/:id/cancel          # Cancel running run

GET    /api/approvals                # List pending approvals
POST   /api/approvals/:id/approve    # Approve an action
POST   /api/approvals/:id/reject     # Reject an action

GET    /api/integrations             # List integrations + status
GET    /api/integrations/:provider/connect   # Start OAuth flow
GET    /api/integrations/:provider/callback  # OAuth callback
DELETE /api/integrations/:provider   # Disconnect integration

GET    /api/dashboard/kpis           # Aggregate KPI data
GET    /api/dashboard/usage          # Usage and cost data

GET    /api/notifications            # List notifications
PATCH  /api/notifications/:id/read   # Mark as read
PATCH  /api/notifications/read-all   # Mark all as read
```

### SSE Chat Endpoint

```python
# apps/api/routers/chat.py
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
import json

router = APIRouter()

@router.post("/chat/stream")
async def chat_stream(request: ChatRequest, user=Depends(get_current_user)):
    run_id = str(uuid4())
    thread_id = request.thread_id or str(uuid4())

    # Create run record
    await db.agent_runs.create({
        "id": run_id,
        "org_id": user.org_id,
        "thread_id": thread_id,
        "agent_id": request.agent_id,
        "status": "running",
        "input": {"message": request.message}
    })

    async def event_stream():
        agent = get_agent(request.agent_slug)
        tracker = RunTracker(run_id, user.org_id)

        async for event in tracker.track(agent, request.to_input(), thread_id):
            # Convert LangGraph events to UI events
            ui_event = map_to_ui_event(event)
            if ui_event:
                yield f"data: {json.dumps(ui_event)}\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable Nginx buffering
        }
    )
```

---

## 13. Real-Time Architecture

Two real-time channels:

**SSE (Server-Sent Events)** — for active chat sessions. Tokens stream as they're generated. Tool call status updates in real time. This connection is per-tab and lives for the duration of the chat session.

**Supabase Realtime** — for background updates. Task status changes, new notifications, approval requests, run completions. This is a persistent websocket connection for the whole app session. Any background agent run that completes while the user is on a different tab will push a notification immediately.

```typescript
// apps/web/lib/realtime.ts
import { createClient } from '@supabase/supabase-js'

export function subscribeToOrgUpdates(orgId: string, handlers: RealtimeHandlers) {
  const supabase = createClient(...)

  // Tasks channel
  supabase
    .channel(`org:${orgId}:tasks`)
    .on('postgres_changes', {
      event: 'UPDATE',
      schema: 'public',
      table: 'tasks',
      filter: `org_id=eq.${orgId}`
    }, payload => handlers.onTaskUpdate(payload.new))
    .subscribe()

  // Notifications channel
  supabase
    .channel(`org:${orgId}:notifications`)
    .on('postgres_changes', {
      event: 'INSERT',
      schema: 'public',
      table: 'notifications',
      filter: `org_id=eq.${orgId}`
    }, payload => handlers.onNewNotification(payload.new))
    .subscribe()

  // Approvals channel
  supabase
    .channel(`org:${orgId}:approvals`)
    .on('postgres_changes', {
      event: 'INSERT',
      schema: 'public',
      table: 'approvals',
      filter: `org_id=eq.${orgId}`
    }, payload => handlers.onApprovalNeeded(payload.new))
    .subscribe()
}
```

---

## 14. Security & Compliance

**Auth:**
- JWT with short expiry (1h) + refresh tokens (30d) stored in httpOnly cookies
- OAuth tokens encrypted at rest using AES-256 before DB storage
- API keys hashed with bcrypt, never returned after creation

**Data isolation:**
- Row Level Security on every sensitive table
- `org_id` required on every query — enforced at ORM level, double-checked by RLS
- No cross-org data accessible via any API endpoint

**Integrations:**
- OAuth tokens stored encrypted in `integrations` table
- Refresh handled server-side only, tokens never exposed to frontend
- Scopes requested are minimal (only what each agent actually needs)
- Users can revoke at any time

**Agent safety:**
- `interrupt_before` on all tools that write to external services
- Approval required for: sending email, posting to social, publishing content, creating calendar events
- Configurable per-org: admins can whitelist specific tools for auto-approval
- All tool calls logged with full input/output for audit trail
- Rate limiting per org per agent (configurable)

**Compliance notes for creator clients:**
- YouTube API compliance: respect quota limits, no scraping, data usage per ToS
- GDPR: data deletion flow — deleting an org cascades to all tables including agent memory
- No PII stored in agent memory embeddings — content only, no email addresses or personal details

---

## 15. MVP Build Order

Work sequentially. Each phase is shippable and demonstrable.

### Phase 1 — Foundation (Week 1–2)
**Goal: A working chat that streams from a real agent**

- [ ] Set up monorepo (Turborepo, pnpm workspaces)
- [ ] Supabase project + run migration 001 (core tables)
- [ ] Supabase Auth + basic login/signup page
- [ ] Next.js app shell: layout, sidebar, auth guard
- [ ] FastAPI app: basic structure, auth middleware, health check
- [ ] General Assistant agent: basic ReAct agent with 2–3 tools
- [ ] SSE streaming endpoint in FastAPI
- [ ] Chat UI: message list, streaming renderer, input box
- [ ] Thread creation and persistence
- [ ] Deploy: Vercel (web) + Railway (api)

**Shippable demo:** Working chat with a streaming AI assistant. Threads persist. Deployable URL.

---

### Phase 2 — Agents + Visibility (Week 3–4)
**Goal: Tool calls are visible, runs are inspectable**

- [ ] Tool call card component (live updates via SSE)
- [ ] `agent_runs` table + RunTracker middleware
- [ ] Run list page (`/runs`)
- [ ] Run detail / pipeline inspector page
- [ ] Content Research agent (web search + YouTube search tools)
- [ ] Agent management page (list, enable/disable, basic config)
- [ ] Task creation (manual + agent-triggered)
- [ ] Task list page with status filtering

**Shippable demo:** Full agent run visibility. Clients can see every tool call. Tasks are tracked.

---

### Phase 3 — Human-in-the-Loop + Approvals (Week 5)
**Goal: Agents pause and wait for approval before consequential actions**

- [ ] `approvals` table
- [ ] `interrupt_before` wired up in BaseAgent
- [ ] Approval request card in chat UI
- [ ] Approve/reject API endpoints
- [ ] Graph resume on approval
- [ ] Approvals page (`/approvals`)
- [ ] Real-time approval notifications (Supabase Realtime)

**Shippable demo:** Agent pauses, shows "waiting for approval" card, user approves, agent continues.

---

### Phase 4 — Projects + KPIs (Week 6)
**Goal: Work is organized, performance is visible**

- [ ] Projects CRUD
- [ ] Project board (Kanban)
- [ ] Link tasks to projects
- [ ] Dashboard page: KPI cards + run charts
- [ ] Usage log aggregation queries
- [ ] Cost tracking per agent

---

### Phase 5 — Integrations (Week 7–8)
**Goal: Agents can act on real external services**

- [ ] Google OAuth flow (Gmail + Docs + Calendar)
- [ ] YouTube Data API integration
- [ ] Gmail tools: search, send (with approval)
- [ ] YouTube tools: search, analytics, get video
- [ ] Slack OAuth + post_message tool (with approval)
- [ ] Integration management UI (`/settings/integrations`)

**Shippable demo:** Agent researches YouTube trends, drafts a Google Doc, posts to Slack — all with approval gates.

---

### Phase 6 — Notifications + Polish (Week 9)
**Goal: Platform feels complete, production-ready**

- [ ] In-app notification center
- [ ] Email notifications via Resend
- [ ] Notification preferences UI
- [ ] Org settings + team management
- [ ] Error handling + retry UI
- [ ] Loading states + empty states throughout
- [ ] Mobile responsive layout
- [ ] End-to-end testing of happy paths

---

## 16. Folder Structure (Full)

```
agentos/
├── apps/
│   ├── web/
│   │   ├── app/
│   │   │   ├── (auth)/
│   │   │   │   ├── login/page.tsx
│   │   │   │   └── signup/page.tsx
│   │   │   ├── (app)/
│   │   │   │   ├── layout.tsx              # App shell with sidebar
│   │   │   │   ├── page.tsx                # Redirect to /chat
│   │   │   │   ├── chat/
│   │   │   │   │   ├── page.tsx            # New chat
│   │   │   │   │   └── [threadId]/page.tsx # Chat thread
│   │   │   │   ├── agents/
│   │   │   │   │   ├── page.tsx            # Agent gallery
│   │   │   │   │   └── [slug]/page.tsx     # Agent detail + config
│   │   │   │   ├── tasks/
│   │   │   │   │   ├── page.tsx            # Task list
│   │   │   │   │   └── [id]/page.tsx       # Task detail
│   │   │   │   ├── projects/
│   │   │   │   │   ├── page.tsx            # Project list
│   │   │   │   │   └── [id]/page.tsx       # Project board
│   │   │   │   ├── runs/
│   │   │   │   │   ├── page.tsx            # Run list
│   │   │   │   │   └── [id]/page.tsx       # Run inspector
│   │   │   │   ├── approvals/page.tsx      # Approval queue
│   │   │   │   ├── dashboard/page.tsx      # KPI dashboard
│   │   │   │   └── settings/
│   │   │   │       ├── integrations/page.tsx
│   │   │   │       ├── team/page.tsx
│   │   │   │       └── notifications/page.tsx
│   │   │   └── api/
│   │   │       └── integrations/
│   │   │           └── [provider]/
│   │   │               └── callback/route.ts  # OAuth callback handler
│   │   ├── components/
│   │   │   ├── chat/
│   │   │   │   ├── ChatWindow.tsx
│   │   │   │   ├── MessageList.tsx
│   │   │   │   ├── MessageBubble.tsx
│   │   │   │   ├── ToolCallCard.tsx
│   │   │   │   ├── ApprovalCard.tsx
│   │   │   │   ├── ChatInput.tsx
│   │   │   │   └── AgentThinking.tsx
│   │   │   ├── inspector/
│   │   │   │   ├── RunTimeline.tsx
│   │   │   │   ├── StepCard.tsx
│   │   │   │   └── ToolCallDetail.tsx
│   │   │   ├── dashboard/
│   │   │   │   ├── KpiCard.tsx
│   │   │   │   ├── RunsChart.tsx
│   │   │   │   └── CostDonut.tsx
│   │   │   ├── layout/
│   │   │   │   ├── Sidebar.tsx
│   │   │   │   ├── TopBar.tsx
│   │   │   │   └── NotificationCenter.tsx
│   │   │   └── ui/                         # Re-exports from packages/ui
│   │   ├── hooks/
│   │   │   ├── useChat.ts                  # SSE chat stream hook
│   │   │   ├── useRealtime.ts              # Supabase realtime subscriptions
│   │   │   └── useApprovals.ts
│   │   ├── lib/
│   │   │   ├── supabase.ts
│   │   │   ├── api.ts                      # Typed fetch wrapper for FastAPI
│   │   │   └── sse.ts                      # SSE client utilities
│   │   └── stores/
│   │       ├── chat.ts                     # Zustand chat state
│   │       ├── notifications.ts
│   │       └── ui.ts
│   │
│   ├── api/
│   │   ├── main.py
│   │   ├── routers/
│   │   │   ├── chat.py
│   │   │   ├── agents.py
│   │   │   ├── tasks.py
│   │   │   ├── projects.py
│   │   │   ├── runs.py
│   │   │   ├── approvals.py
│   │   │   ├── integrations.py
│   │   │   ├── notifications.py
│   │   │   └── dashboard.py
│   │   ├── middleware/
│   │   │   ├── auth.py
│   │   │   └── ratelimit.py
│   │   ├── dependencies.py
│   │   ├── worker.py
│   │   └── Dockerfile
│   │
│   └── workers/
│       ├── tasks.py                        # Celery task definitions
│       ├── scheduled.py                    # APScheduler jobs
│       └── Dockerfile
│
├── packages/
│   ├── agents/
│   │   ├── core/
│   │   │   ├── base.py
│   │   │   ├── tracker.py
│   │   │   ├── tools.py                    # Shared utility tools
│   │   │   └── prompts.py                  # Base system prompts
│   │   ├── general/
│   │   │   ├── agent.py
│   │   │   ├── tools.py
│   │   │   ├── manifest.json
│   │   │   └── prompts.py
│   │   └── content-research/
│   │       ├── agent.py
│   │       ├── tools.py
│   │       ├── manifest.json
│   │       └── prompts.py
│   │
│   ├── integrations/
│   │   ├── base.py
│   │   ├── google/
│   │   │   ├── auth.py
│   │   │   ├── gmail.py
│   │   │   ├── docs.py
│   │   │   └── calendar.py
│   │   ├── youtube/
│   │   │   ├── auth.py
│   │   │   └── client.py
│   │   └── slack/
│   │       ├── auth.py
│   │       └── client.py
│   │
│   ├── db/
│   │   ├── migrations/
│   │   │   └── 001_core.sql
│   │   ├── client.py                       # Async Supabase client
│   │   └── client.ts                       # Typed Supabase client (Next.js)
│   │
│   ├── ui/
│   │   ├── components/                     # shadcn/ui exports + custom
│   │   └── package.json
│   │
│   └── shared/
│       ├── types.ts                        # Shared TypeScript types
│       ├── types.py                        # Pydantic models (mirrors TS types)
│       └── constants.ts
│
├── infra/
│   ├── docker-compose.yml
│   └── supabase/
│       └── config.toml
│
├── turbo.json
├── package.json
└── pyproject.toml
```

---

## 17. Environment Variables

```bash
# ── Supabase ──────────────────────────────
NEXT_PUBLIC_SUPABASE_URL=https://xxxx.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJ...
SUPABASE_SERVICE_KEY=eyJ...            # Server-side only
DATABASE_URL=postgresql://...          # For LangGraph checkpointer

# ── Anthropic ─────────────────────────────
ANTHROPIC_API_KEY=sk-ant-...

# ── Redis (Upstash) ───────────────────────
REDIS_URL=redis://...
UPSTASH_REDIS_REST_URL=https://...
UPSTASH_REDIS_REST_TOKEN=...

# ── Email (Resend) ─────────────────────────
RESEND_API_KEY=re_...
EMAIL_FROM=notifications@yourdomain.com

# ── Google OAuth ──────────────────────────
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=https://yourdomain.com/api/integrations/google/callback

# ── YouTube ───────────────────────────────
YOUTUBE_API_KEY=...                    # For public data (no OAuth)

# ── Slack OAuth ───────────────────────────
SLACK_CLIENT_ID=...
SLACK_CLIENT_SECRET=...
SLACK_REDIRECT_URI=https://yourdomain.com/api/integrations/slack/callback

# ── Encryption ────────────────────────────
ENCRYPTION_KEY=...                     # AES-256 key for OAuth token encryption

# ── App ───────────────────────────────────
NEXT_PUBLIC_APP_URL=https://yourdomain.com
API_URL=https://api.yourdomain.com
JWT_SECRET=...
ENVIRONMENT=production                 # development | staging | production

# ── n8n ───────────────────────────────────
N8N_URL=https://n8n.yourdomain.com
N8N_API_KEY=...
```

---

## 18. Deployment

### Local Development

```bash
# Install dependencies
pnpm install
pip install poetry
poetry install

# Start all services
docker-compose up -d          # Postgres, Redis, n8n
pnpm dev                      # Turborepo: runs web + api concurrently

# Run DB migrations
supabase db push

# Seed development data
pnpm run db:seed
```

### Production

**Frontend (Vercel):**
```bash
vercel --prod
# Set all NEXT_PUBLIC_* env vars in Vercel dashboard
```

**API + Workers (Railway):**
```dockerfile
# apps/api/Dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY . .
RUN pip install -r requirements.txt

# API service
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

# Worker service (different Railway service, same image)
# CMD ["celery", "-A", "worker", "worker", "--loglevel=info"]
```

Railway runs two services from the same Docker image with different start commands — one for the FastAPI server, one for the Celery worker.

**n8n (DigitalOcean $5 droplet):**
```bash
docker run -d --name n8n \
  --restart unless-stopped \
  -p 5678:5678 \
  -v ~/.n8n:/home/node/.n8n \
  n8nio/n8n
```

---

## 19. Scale Considerations

**When you hit 10 clients:**
- Everything described here handles this comfortably on the cheapest tier of each service
- Estimated monthly infra cost: $40–80 (Vercel free, Railway $10, Supabase free/pro $25, Upstash $10, Resend free)

**When you hit 50 clients:**
- Add Postgres connection pooling (PgBouncer via Supabase)
- Move Celery workers to a dedicated Railway service with auto-scaling
- Add rate limiting per org to prevent one heavy client from affecting others
- Add Supabase read replica for dashboard queries

**When you hit 200+ clients:**
- Consider moving LangGraph checkpointing off Supabase to a dedicated Postgres instance
- Add a CDN layer for the frontend (Vercel handles this automatically)
- Add observability: Sentry for errors, PostHog for product analytics, Langfuse for LLM observability
- Consider multi-region deployment for latency (Fly.io handles this well)

**LLM cost at scale:**
- Per active client per month: $20–60 in API costs for moderate usage
- At 50 clients: $1,000–3,000/month in API costs against $25,000–45,000 MRR
- Cost ratio stays under 10% if you use Haiku for high-volume tasks and Sonnet only for quality-critical ones

**The most important scale decision:** Keep the agent orchestration stateless at the application layer. All state lives in Supabase (via LangGraph checkpointer). This means you can run 10 API replicas without any shared memory issues — every request fetches state from Postgres and writes it back. Horizontal scaling is free.
