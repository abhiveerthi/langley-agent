"use client";

import { useState } from "react";
import { Send, Play, Database, Mail, HardDrive, Globe, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

const conversations = [
  { id: "1", title: "YouTube SEO Strategy Q&A", time: "2h ago", active: true },
  { id: "2", title: "Script for AI Tools video", time: "Yesterday" },
  { id: "3", title: "Brand deal with Notion draft", time: "2d ago" },
  { id: "4", title: "Trending topic research", time: "3d ago" },
  { id: "5", title: "Channel growth deep dive", time: "1w ago" },
];

const messages = [
  {
    id: "1",
    role: "user",
    content: "What are the best SEO strategies for my YouTube channel right now in 2025?",
    time: "2:14 PM",
  },
  {
    id: "2",
    role: "assistant",
    content: `Great question. Based on your channel's analytics and current YouTube trends, here are the top strategies that will move the needle:\n\n**1. Optimize for Search Intent First**\nYouTube's algorithm now heavily weighs viewer satisfaction signals. Titles should match exactly what searchers type — "how to" and "step by step" prefixes are outperforming clickbait by 34% in your niche.\n\n**2. Front-load Keywords in Descriptions**\nYour first 2–3 sentences are indexed most heavily. I've analyzed your last 10 videos — you're burying keywords in paragraph 3. Moving them to the opener could lift impressions by an estimated 18–22%.\n\n**3. Chapters = Longer Watch Time**\nVideos with timestamp chapters average 23% higher average view duration. Your last upload had none — I can auto-generate them from your transcript.\n\n**4. Tag Strategy Has Shifted**\nUse 5–8 highly specific tags rather than 15 broad ones. I've queued up a tag set for your next video based on search volume data.`,
    time: "2:14 PM",
  },
  {
    id: "3",
    role: "user",
    content: "Can you generate an optimized title for my upcoming AI tools video?",
    time: "2:16 PM",
  },
  {
    id: "4",
    role: "assistant",
    content: `Here are **4 title options** ranked by predicted CTR based on your audience and current search trends:\n\n1. **"I Used AI to Build a $10K YouTube Channel (Step by Step)"** — Score: 94 | High search volume, strong curiosity gap\n2. **"10 AI Tools Every YouTuber Needs in 2025"** — Score: 88 | List format performs well for your audience\n3. **"How AI Changed My YouTube Strategy Forever"** — Score: 79 | Personal narrative, good for returning viewers\n4. **"The Ultimate AI YouTube Workflow (2025 Guide)"** — Score: 71 | High competition keyword but solid intent match\n\nI recommend **Option 1** — it combines specificity, a dollar anchor, and proof of results. Want me to also generate matching thumbnail text and description?`,
    time: "2:16 PM",
  },
  {
    id: "5",
    role: "user",
    content: "Yes, generate the thumbnail text and a full description too.",
    time: "2:17 PM",
  },
];

const skills = [
  "Generate Script",
  "Analyze Video",
  "Find Trends",
  "Optimize SEO",
  "Draft Brand Reply",
  "Research Topic",
];

const tools = [
  { name: "YouTube Analytics", icon: Play, connected: true },
  { name: "RAG Knowledge Base", icon: Database, connected: true },
  { name: "Gmail", icon: Mail, connected: true },
  { name: "Dropbox", icon: HardDrive, connected: true },
  { name: "Web Search", icon: Globe, connected: true },
];

const highlightedSkills = [
  { name: "SEO Optimizer", desc: "Generate titles, tags & descriptions" },
  { name: "Script Writer", desc: "Write in your voice and style" },
  { name: "Trend Finder", desc: "Spot opportunities before they peak" },
];

export default function ChatPage() {
  const [activeConv, setActiveConv] = useState("1");
  const [input, setInput] = useState("");

  return (
    <div className="flex h-full overflow-hidden">
      {/* Left sidebar — conversations */}
      <div className="flex w-52 shrink-0 flex-col border-r border-border bg-sidebar">
        <div className="border-b border-border px-4 py-3">
          <p className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Conversations
          </p>
        </div>
        <div className="flex-1 overflow-y-auto py-2">
          {conversations.map((conv) => (
            <button
              key={conv.id}
              onClick={() => setActiveConv(conv.id)}
              className={cn(
                "w-full px-3 py-2.5 text-left transition-colors hover:bg-accent",
                activeConv === conv.id && "bg-primary/10"
              )}
            >
              <p
                className={cn(
                  "truncate text-xs font-medium leading-snug",
                  activeConv === conv.id ? "text-primary" : "text-foreground"
                )}
              >
                {conv.title}
              </p>
              <p className="mt-0.5 text-xs text-muted-foreground">{conv.time}</p>
            </button>
          ))}
        </div>
      </div>

      {/* Main chat area */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Messages */}
        <div className="flex-1 overflow-y-auto px-6 py-6 space-y-6">
          {messages.map((msg) => (
            <div
              key={msg.id}
              className={cn("flex gap-3", msg.role === "user" ? "justify-end" : "justify-start")}
            >
              {msg.role === "assistant" && (
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/20 text-xs font-bold text-primary">
                  AI
                </div>
              )}
              <div
                className={cn(
                  "max-w-[75%] rounded-2xl px-4 py-3 text-sm leading-relaxed",
                  msg.role === "user"
                    ? "bg-primary text-primary-foreground rounded-tr-sm"
                    : "bg-card border border-border text-foreground rounded-tl-sm"
                )}
              >
                {msg.role === "assistant" ? (
                  <div className="space-y-2 whitespace-pre-line">
                    {msg.content.split("\n").map((line, i) => {
                      const boldLine = line.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
                      return (
                        <p
                          key={i}
                          dangerouslySetInnerHTML={{ __html: boldLine }}
                          className={line.startsWith("**") && line.endsWith("**") ? "font-semibold" : ""}
                        />
                      );
                    })}
                  </div>
                ) : (
                  <p>{msg.content}</p>
                )}
              </div>
              {msg.role === "user" && (
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/20 text-xs font-semibold text-primary">
                  SR
                </div>
              )}
            </div>
          ))}
          {/* Typing indicator */}
          <div className="flex gap-3 justify-start">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/20 text-xs font-bold text-primary">
              AI
            </div>
            <div className="flex items-center gap-1.5 rounded-2xl rounded-tl-sm border border-border bg-card px-4 py-3">
              <span className="h-2 w-2 animate-bounce rounded-full bg-muted-foreground [animation-delay:0ms]" />
              <span className="h-2 w-2 animate-bounce rounded-full bg-muted-foreground [animation-delay:150ms]" />
              <span className="h-2 w-2 animate-bounce rounded-full bg-muted-foreground [animation-delay:300ms]" />
            </div>
          </div>
        </div>

        {/* Input area */}
        <div className="border-t border-border bg-background px-6 py-4">
          {/* Skill chips */}
          <div className="mb-3 flex gap-2 overflow-x-auto pb-1 scrollbar-none">
            {skills.map((skill) => (
              <button
                key={skill}
                className="shrink-0 rounded-full border border-border bg-card px-3 py-1 text-xs font-medium text-muted-foreground transition-colors hover:border-primary/50 hover:text-primary"
              >
                {skill}
              </button>
            ))}
          </div>
          {/* Textarea + send */}
          <div className="flex items-end gap-3">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask anything about your channel..."
              rows={2}
              className="flex-1 resize-none rounded-lg border border-border bg-card px-4 py-3 text-sm text-foreground placeholder:text-muted-foreground focus:border-primary/50 focus:outline-none"
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                }
              }}
            />
            <button className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground transition-colors hover:bg-primary/90">
              <Send className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>

      {/* Right panel */}
      <div className="flex w-72 shrink-0 flex-col border-l border-border bg-sidebar overflow-y-auto">
        {/* Tools */}
        <div className="border-b border-border p-4">
          <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Tools
          </p>
          <div className="space-y-2">
            {tools.map((tool) => (
              <div key={tool.name} className="flex items-center gap-2.5">
                <div className="flex h-7 w-7 items-center justify-center rounded-md bg-muted">
                  <tool.icon className="h-3.5 w-3.5 text-muted-foreground" />
                </div>
                <span className="flex-1 text-xs text-foreground">{tool.name}</span>
                <div
                  className={cn(
                    "h-1.5 w-1.5 rounded-full",
                    tool.connected ? "bg-emerald-500" : "bg-muted-foreground/40"
                  )}
                />
              </div>
            ))}
          </div>
        </div>

        {/* Context */}
        <div className="border-b border-border p-4">
          <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Context
          </p>
          <div className="rounded-lg bg-muted/50 p-3 text-xs space-y-2">
            <div className="flex justify-between text-muted-foreground">
              <span>Current video</span>
              <span className="font-medium text-foreground truncate max-w-[120px]">AI Tools video</span>
            </div>
            <div className="flex justify-between text-muted-foreground">
              <span>Script length</span>
              <span className="font-medium text-foreground">2,840 words</span>
            </div>
            <div className="flex justify-between text-muted-foreground">
              <span>Est. duration</span>
              <span className="font-medium text-foreground">~19 min</span>
            </div>
            <div className="flex justify-between text-muted-foreground">
              <span>SEO score</span>
              <span className="font-medium text-emerald-400">82 / 100</span>
            </div>
          </div>
        </div>

        {/* Skills */}
        <div className="p-4">
          <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Skills
          </p>
          <div className="space-y-2">
            {highlightedSkills.map((skill) => (
              <button
                key={skill.name}
                className="w-full rounded-lg border border-border bg-card p-3 text-left transition-colors hover:border-primary/40 hover:bg-accent group"
              >
                <div className="flex items-center justify-between">
                  <p className="text-xs font-medium text-foreground">{skill.name}</p>
                  <ChevronRight className="h-3 w-3 text-muted-foreground group-hover:text-primary" />
                </div>
                <p className="mt-0.5 text-xs text-muted-foreground">{skill.desc}</p>
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
