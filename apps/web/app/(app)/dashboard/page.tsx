import Link from "next/link";
import { Upload, Scissors, Image, FileText, TrendingUp, ArrowUpRight } from "lucide-react";
import { channelStats, recentVideos } from "@/lib/mock-data";
import { cn } from "@/lib/utils";

const gradients = [
  "bg-linear-to-br from-violet-600 to-indigo-800",
  "bg-linear-to-br from-emerald-600 to-teal-800",
  "bg-linear-to-br from-orange-500 to-red-700",
  "bg-linear-to-br from-pink-600 to-purple-800",
  "bg-linear-to-br from-blue-600 to-cyan-800",
  "bg-linear-to-br from-amber-500 to-orange-700",
];

const activeTasks = [
  { label: "Generating Spanish dub for 'AI Tools...'", progress: 67, color: "bg-indigo-500" },
  { label: "Clipping Shorts from 'Passive Income...'", progress: 100, color: "bg-emerald-500" },
  { label: "Optimizing SEO for draft video", progress: 23, color: "bg-amber-500" },
];

const quickActions = [
  { label: "Upload Video", icon: Upload, href: "/studio/clips", color: "text-indigo-400" },
  { label: "Generate Clips", icon: Scissors, href: "/studio/clips", color: "text-violet-400" },
  { label: "Create Thumbnail", icon: Image, href: "/studio/thumbnails", color: "text-pink-400" },
  { label: "Write Script", icon: FileText, href: "/studio/scripts", color: "text-emerald-400" },
];

const sparklineBars = [40, 60, 45, 70, 55, 80, 65, 90, 75, 100];

function StatCard({
  label,
  value,
  change,
  trend,
}: {
  label: string;
  value: string;
  change: string;
  trend: string;
}) {
  const isUp = trend === "up";
  return (
    <div className="rounded-lg border border-border bg-card p-5">
      <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className="mt-2 text-3xl font-bold tracking-tight text-foreground">{value}</p>
      <div className="mt-3 flex items-center justify-between">
        <span
          className={cn(
            "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
            isUp ? "bg-emerald-500/15 text-emerald-400" : "bg-red-500/15 text-red-400"
          )}
        >
          <TrendingUp className={cn("h-3 w-3", !isUp && "rotate-180")} />
          {change}
        </span>
        {/* Decorative sparkline */}
        <div className="flex items-end gap-0.5">
          {sparklineBars.map((h, i) => (
            <div
              key={i}
              className="w-1 rounded-sm bg-primary/30"
              style={{ height: `${(h / 100) * 24}px` }}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

export default function DashboardPage() {
  return (
    <div className="p-6 space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Dashboard</h1>
        <p className="mt-1 text-sm text-muted-foreground">Your channel at a glance</p>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Total Views" {...channelStats.views} />
        <StatCard label="Subscribers" {...channelStats.subscribers} />
        <StatCard label="Revenue" {...channelStats.revenue} />
        <StatCard label="Videos Published" {...channelStats.videos} />
      </div>

      {/* Quick Actions */}
      <div>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted-foreground">
          Quick Actions
        </h2>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {quickActions.map((action) => (
            <Link
              key={action.label}
              href={action.href}
              className="flex flex-col items-center gap-3 rounded-lg border border-border bg-card p-5 text-center transition-colors hover:border-primary/40 hover:bg-accent"
            >
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-muted">
                <action.icon className={cn("h-5 w-5", action.color)} />
              </div>
              <span className="text-sm font-medium text-foreground">{action.label}</span>
            </Link>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Recent Videos */}
        <div className="lg:col-span-2">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
              Recent Videos
            </h2>
            <Link href="/dashboard" className="flex items-center gap-1 text-xs text-primary hover:underline">
              View all <ArrowUpRight className="h-3 w-3" />
            </Link>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {recentVideos.map((video, i) => (
              <div
                key={video.id}
                className="rounded-lg border border-border bg-card overflow-hidden hover:border-border/80 transition-colors"
              >
                {/* Thumbnail */}
                <div className={cn("h-28 relative", gradients[i % gradients.length])}>
                  {video.status === "processing" && (
                    <div className="absolute inset-0 flex items-center justify-center bg-black/40">
                      <div className="flex items-center gap-2 rounded-full bg-amber-500/90 px-3 py-1 text-xs font-medium text-white">
                        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-white" />
                        Processing
                      </div>
                    </div>
                  )}
                  {video.status === "draft" && (
                    <div className="absolute inset-0 flex items-center justify-center bg-black/40">
                      <div className="rounded-full bg-zinc-600/90 px-3 py-1 text-xs font-medium text-white">
                        Draft
                      </div>
                    </div>
                  )}
                  {video.duration && (
                    <div className="absolute bottom-1.5 right-1.5 rounded bg-black/70 px-1.5 py-0.5 text-xs text-white">
                      {video.duration}
                    </div>
                  )}
                </div>
                {/* Info */}
                <div className="p-3">
                  <p className="line-clamp-2 text-sm font-medium text-foreground leading-snug">
                    {video.title}
                  </p>
                  {video.status === "published" && (
                    <div className="mt-2 flex items-center gap-3 text-xs text-muted-foreground">
                      <span>{video.views} views</span>
                      <span>CTR {video.ctr}</span>
                      <span>{video.publishedAt}</span>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Active AI Tasks */}
        <div>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted-foreground">
            Active AI Tasks
          </h2>
          <div className="rounded-lg border border-border bg-card p-4 space-y-5">
            {activeTasks.map((task, i) => (
              <div key={i}>
                <div className="mb-1.5 flex items-center justify-between">
                  <p className="text-xs text-foreground leading-snug">{task.label}</p>
                  <span className="ml-2 shrink-0 text-xs font-medium text-muted-foreground">
                    {task.progress}%
                  </span>
                </div>
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                  <div
                    className={cn("h-full rounded-full transition-all", task.color)}
                    style={{ width: `${task.progress}%` }}
                  />
                </div>
              </div>
            ))}
            <div className="mt-4 rounded-md bg-muted/50 px-3 py-2">
              <p className="text-xs text-muted-foreground">
                <span className="font-medium text-foreground">3</span> tasks running &middot; Avg completion in <span className="font-medium text-foreground">~4 min</span>
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
