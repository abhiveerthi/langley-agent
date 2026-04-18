import { AlertTriangle, Play, TrendingUp } from "lucide-react";
import { trendingTopics } from "@/lib/mock-data";
import { cn } from "@/lib/utils";

const trendingAudio = [
  { title: "Upbeat Tech Vibes", artist: "Artlist Original", uses: "142K", bars: [30, 60, 40, 80, 50, 90, 45, 70, 55, 85, 35, 75] },
  { title: "Lo-fi Creator Beat", artist: "Epidemic Sound", uses: "89K", bars: [50, 40, 70, 30, 80, 45, 90, 35, 65, 55, 80, 40] },
  { title: "Cinematic Rise", artist: "Musicbed", uses: "67K", bars: [20, 50, 35, 75, 60, 85, 40, 70, 55, 90, 30, 65] },
];

function opportunityStyle(opp: string) {
  if (opp === "high") return "bg-emerald-500/15 text-emerald-400";
  return "bg-amber-500/15 text-amber-400";
}

// Decorative SVG niche health trend line
function NicheTrendLine() {
  const points = [
    [0, 40], [15, 35], [25, 45], [40, 30], [55, 38], [65, 20], [80, 25], [100, 13],
  ];
  const pathD = points
    .map((p, i) => `${i === 0 ? "M" : "L"} ${p[0]} ${p[1]}`)
    .join(" ");

  return (
    <svg viewBox="0 0 100 60" className="h-16 w-full" preserveAspectRatio="none">
      <path d={pathD} fill="none" stroke="hsl(var(--primary))" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <path
        d={pathD + " L 100 60 L 0 60 Z"}
        fill="hsl(var(--primary))"
        fillOpacity="0.1"
      />
    </svg>
  );
}

export default function TrendsPage() {
  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Trend Radar</h1>
        <p className="mt-1 text-sm text-muted-foreground">Spot opportunities before they peak</p>
      </div>

      {/* Alert banner */}
      <div className="flex items-center gap-3 rounded-lg bg-primary/10 border border-primary/30 px-4 py-3">
        <AlertTriangle className="h-4 w-4 shrink-0 text-primary" />
        <p className="text-sm text-primary font-medium">
          3 high-opportunity trends detected in your niche — act now while competition is low
        </p>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Trending topics */}
        <div className="lg:col-span-2">
          <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Trending Topics
          </p>
          <div className="rounded-lg border border-border bg-card overflow-hidden divide-y divide-border">
            {trendingTopics.map((topic, i) => (
              <div key={i} className="px-5 py-4">
                <div className="flex items-start justify-between gap-4 mb-2">
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-foreground">{topic.topic}</p>
                    <p className="mt-0.5 text-xs text-muted-foreground">{topic.views7d} views in last 7 days</p>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium capitalize", opportunityStyle(topic.opportunity))}>
                      {topic.opportunity}
                    </span>
                    <button className="flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90">
                      <TrendingUp className="h-3 w-3" />
                      Create Video
                    </button>
                  </div>
                </div>
                {/* Velocity bar */}
                <div className="flex items-center gap-3">
                  <span className="w-16 shrink-0 text-xs text-muted-foreground">Velocity</span>
                  <div className="flex-1 h-1.5 overflow-hidden rounded-full bg-muted">
                    <div
                      className={cn(
                        "h-full rounded-full",
                        topic.velocity >= 90 ? "bg-emerald-500" : topic.velocity >= 80 ? "bg-primary" : "bg-amber-500"
                      )}
                      style={{ width: `${topic.velocity}%` }}
                    />
                  </div>
                  <span className="w-8 shrink-0 text-right text-xs font-medium text-foreground">{topic.velocity}</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Niche health sidebar */}
        <div className="space-y-5">
          <div className="rounded-lg border border-border bg-card p-5">
            <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Niche Health Score
            </p>
            <div className="flex items-end gap-2 mb-2">
              <span className="text-5xl font-bold text-foreground">87</span>
              <span className="mb-2 text-sm font-medium text-emerald-400 flex items-center gap-1">
                <TrendingUp className="h-4 w-4" /> +4 this week
              </span>
            </div>
            <NicheTrendLine />
            <div className="mt-4 space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Active Creators</span>
                <span className="font-medium text-foreground">2,847</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Avg Views/Video</span>
                <span className="font-medium text-foreground">84K</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Avg Sub Count</span>
                <span className="font-medium text-foreground">127K</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Competition</span>
                <span className="font-medium text-amber-400">Medium</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Trending Audio */}
      <div>
        <p className="mb-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Trending Audio
        </p>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          {trendingAudio.map((audio) => (
            <div key={audio.title} className="rounded-lg border border-border bg-card p-4">
              <div className="mb-3 flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium text-foreground">{audio.title}</p>
                  <p className="text-xs text-muted-foreground">{audio.artist}</p>
                </div>
                <button className="flex h-8 w-8 items-center justify-center rounded-full bg-muted hover:bg-accent transition-colors">
                  <Play className="h-3.5 w-3.5 fill-foreground text-foreground ml-0.5" />
                </button>
              </div>
              {/* Waveform */}
              <div className="flex items-center gap-0.5 mb-3">
                {audio.bars.map((h, i) => (
                  <div
                    key={i}
                    className="flex-1 rounded-sm bg-primary/50"
                    style={{ height: `${h * 0.4 + 6}px` }}
                  />
                ))}
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground">{audio.uses} uses</span>
                <button className="rounded-md bg-primary/10 px-3 py-1 text-xs font-medium text-primary hover:bg-primary/20 transition-colors">
                  Use in Short
                </button>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
