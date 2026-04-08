import { ThumbsUp, MessageCircle, ExternalLink } from "lucide-react";
import { commentClusters } from "@/lib/mock-data";
import { cn } from "@/lib/utils";

const topComments = [
  {
    id: "1",
    username: "TechWithMarcus",
    initials: "TM",
    color: "bg-violet-500/20 text-violet-400",
    comment: "This is hands down the most actionable video on AI + YouTube I've seen. Implemented the SEO workflow yesterday, already seeing impressions tick up. Part 2 PLEASE.",
    likes: 847,
    time: "2 days ago",
  },
  {
    id: "2",
    username: "CreatorWithCara",
    initials: "CC",
    color: "bg-pink-500/20 text-pink-400",
    comment: "What AI tool do you use for scripting? I've tried a few but they all sound robotic. Your content sounds so natural — is that all you or is the AI doing heavy lifting?",
    likes: 312,
    time: "3 days ago",
  },
  {
    id: "3",
    username: "SkepticalSteve",
    initials: "SS",
    color: "bg-zinc-500/20 text-zinc-400",
    comment: "Respectfully, these income numbers seem inflated. Would love to see actual AdSense screenshots rather than just graphs. Hard to trust creator income claims these days.",
    likes: 128,
    time: "4 days ago",
  },
];

const aiInsights = [
  { text: "891 viewers requested Part 2 — schedule it in the next 2 weeks to capitalize on momentum.", type: "opportunity" },
  { text: "High skepticism around income claims — consider a follow-up showing real dashboard screenshots.", type: "warning" },
  { text: "Tutorial requests suggest a step-by-step \"setup from scratch\" video would perform exceptionally well.", type: "opportunity" },
];

function sentimentDot(sentiment: string) {
  if (sentiment === "positive") return "bg-emerald-500";
  if (sentiment === "negative") return "bg-red-500";
  return "bg-zinc-500";
}

export default function CommentsPage() {
  // SVG donut chart values
  const total = 100;
  const positive = 73;
  const neutral = 18;
  const negative = 9;

  const r = 52;
  const cx = 70;
  const cy = 70;
  const circumference = 2 * Math.PI * r;

  const positiveLen = (positive / 100) * circumference;
  const neutralLen = (neutral / 100) * circumference;
  const negativeLen = (negative / 100) * circumference;

  // Offsets: start at top (-90deg rotation)
  const positiveOffset = 0;
  const neutralOffset = positiveLen;
  const negativeOffset = positiveLen + neutralLen;

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Comment Intelligence</h1>
        <p className="mt-1 text-sm text-muted-foreground">Understand what your audience is telling you</p>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: "Total Comments", value: "4,832", sub: "Last 30 days" },
          { label: "Positive Sentiment", value: "73%", sub: "+5% vs last month", green: true },
          { label: "Questions", value: "28%", sub: "1,353 unanswered" },
        ].map((stat) => (
          <div key={stat.label} className="rounded-lg border border-border bg-card p-4">
            <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">{stat.label}</p>
            <p className={cn("mt-2 text-3xl font-bold", stat.green ? "text-emerald-400" : "text-foreground")}>
              {stat.value}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">{stat.sub}</p>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Sentiment donut */}
        <div className="rounded-lg border border-border bg-card p-5">
          <p className="mb-4 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Sentiment Analysis
          </p>
          <div className="flex items-center gap-8">
            <div className="relative shrink-0">
              <svg width="140" height="140" viewBox="0 0 140 140">
                {/* Track */}
                <circle cx={cx} cy={cy} r={r} fill="none" stroke="hsl(var(--muted))" strokeWidth="18" />
                {/* Positive */}
                <circle
                  cx={cx} cy={cy} r={r}
                  fill="none" stroke="hsl(var(--primary))" strokeWidth="18"
                  strokeDasharray={`${positiveLen} ${circumference - positiveLen}`}
                  strokeDashoffset={-positiveOffset}
                  transform={`rotate(-90 ${cx} ${cy})`}
                  strokeLinecap="butt"
                />
                {/* Neutral */}
                <circle
                  cx={cx} cy={cy} r={r}
                  fill="none" stroke="hsl(var(--muted-foreground))" strokeWidth="18"
                  strokeDasharray={`${neutralLen} ${circumference - neutralLen}`}
                  strokeDashoffset={-neutralOffset}
                  transform={`rotate(-90 ${cx} ${cy})`}
                  strokeLinecap="butt"
                />
                {/* Negative */}
                <circle
                  cx={cx} cy={cy} r={r}
                  fill="none" stroke="#ef4444" strokeWidth="18"
                  strokeDasharray={`${negativeLen} ${circumference - negativeLen}`}
                  strokeDashoffset={-negativeOffset}
                  transform={`rotate(-90 ${cx} ${cy})`}
                  strokeLinecap="butt"
                />
                <text x={cx} y={cy - 6} textAnchor="middle" fontSize="22" fontWeight="bold" fill="currentColor" className="fill-foreground">73%</text>
                <text x={cx} y={cy + 12} textAnchor="middle" fontSize="10" fill="currentColor" className="fill-muted-foreground">positive</text>
              </svg>
            </div>
            <div className="space-y-3">
              {[
                { label: "Positive", pct: `${positive}%`, color: "bg-primary" },
                { label: "Neutral", pct: `${neutral}%`, color: "bg-muted-foreground" },
                { label: "Negative", pct: `${negative}%`, color: "bg-red-500" },
              ].map((item) => (
                <div key={item.label} className="flex items-center gap-3">
                  <div className={cn("h-3 w-3 rounded-full shrink-0", item.color)} />
                  <span className="text-sm text-foreground">{item.label}</span>
                  <span className="text-sm font-semibold text-foreground">{item.pct}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Topic clusters */}
        <div className="rounded-lg border border-border bg-card p-5">
          <p className="mb-4 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Topic Clusters
          </p>
          <div className="space-y-3">
            {commentClusters.sort((a, b) => b.count - a.count).map((cluster) => (
              <div key={cluster.topic} className="flex items-center gap-3">
                <div className={cn("h-2 w-2 shrink-0 rounded-full", sentimentDot(cluster.sentiment))} />
                <span className="flex-1 text-sm text-foreground">{cluster.topic}</span>
                <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
                  {cluster.count.toLocaleString()}
                </span>
                <button className="flex items-center gap-1 text-xs text-primary hover:underline">
                  View <ExternalLink className="h-2.5 w-2.5" />
                </button>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Top comments */}
      <div>
        <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Top Comments
        </p>
        <div className="space-y-3">
          {topComments.map((comment) => (
            <div key={comment.id} className="rounded-lg border border-border bg-card p-4">
              <div className="flex items-start gap-3">
                <div className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-xs font-semibold", comment.color)}>
                  {comment.initials}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-sm font-medium text-foreground">{comment.username}</span>
                    <span className="text-xs text-muted-foreground">{comment.time}</span>
                  </div>
                  <p className="text-sm text-muted-foreground leading-relaxed">{comment.comment}</p>
                  <div className="mt-2 flex items-center gap-4">
                    <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                      <ThumbsUp className="h-3 w-3" /> {comment.likes.toLocaleString()}
                    </span>
                    <button className="flex items-center gap-1.5 text-xs text-primary hover:underline">
                      <MessageCircle className="h-3 w-3" /> Reply
                    </button>
                  </div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* AI Insights */}
      <div>
        <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          AI Insights
        </p>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          {aiInsights.map((insight, i) => (
            <div
              key={i}
              className={cn(
                "rounded-lg border p-4",
                insight.type === "opportunity"
                  ? "border-primary/30 bg-primary/5"
                  : "border-amber-500/30 bg-amber-500/5"
              )}
            >
              <p className="text-sm text-foreground leading-snug">{insight.text}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
