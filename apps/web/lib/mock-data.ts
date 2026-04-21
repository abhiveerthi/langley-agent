// Channel stats
export const channelStats = {
  views: { value: "2.4M", change: "+12%", trend: "up" },
  subscribers: { value: "847K", change: "+3.2%", trend: "up" },
  revenue: { value: "$12,400", change: "+8.1%", trend: "up" },
  videos: { value: "24", change: "+4", trend: "up" },
}

// Recent videos (6 items)
export const recentVideos = [
  { id: "1", title: "10 AI Tools That Changed My Workflow Forever", views: "284K", duration: "18:24", publishedAt: "2 days ago", thumbnail: null, status: "published", ctr: "7.2%", avgView: "68%" },
  { id: "2", title: "I Tried Every AI Video Editor So You Don't Have To", views: "156K", duration: "22:10", publishedAt: "5 days ago", thumbnail: null, status: "published", ctr: "6.8%", avgView: "71%" },
  { id: "3", title: "The Truth About Passive Income on YouTube", views: "91K", duration: "14:33", publishedAt: "1 week ago", thumbnail: null, status: "published", ctr: "9.1%", avgView: "54%" },
  { id: "4", title: "Building a $10K/Month Creator Business (Full Breakdown)", views: "412K", duration: "31:05", publishedAt: "2 weeks ago", thumbnail: null, status: "published", ctr: "8.4%", avgView: "62%" },
  { id: "5", title: "YouTube Algorithm 2025: What Actually Works", views: null, duration: null, publishedAt: null, thumbnail: null, status: "processing", ctr: null, avgView: null },
  { id: "6", title: "How I Script 30 Videos Per Month with AI", views: null, duration: null, publishedAt: null, thumbnail: null, status: "draft", ctr: null, avgView: null },
]

// Generated clips
export const generatedClips = [
  { id: "1", title: "AI tools changed my life moment", score: 94, duration: "0:47", platform: ["shorts", "reels", "tiktok"] },
  { id: "2", title: "The $10K secret nobody talks about", score: 88, duration: "0:58", platform: ["shorts", "tiktok"] },
  { id: "3", title: "Passive income reality check", score: 76, duration: "1:02", platform: ["shorts"] },
  { id: "4", title: "Algorithm hack that actually works", score: 71, duration: "0:43", platform: ["shorts", "reels"] },
]

// Dubbing languages
export const dubbingLanguages = [
  { code: "es", name: "Spanish", flag: "🇪🇸", subscribers: "120M+", status: "ready" },
  { code: "pt", name: "Portuguese", flag: "🇧🇷", subscribers: "210M+", status: "ready" },
  { code: "hi", name: "Hindi", flag: "🇮🇳", subscribers: "600M+", status: "beta" },
  { code: "fr", name: "French", flag: "🇫🇷", subscribers: "80M+", status: "ready" },
  { code: "de", name: "German", flag: "🇩🇪", subscribers: "90M+", status: "ready" },
  { code: "ja", name: "Japanese", flag: "🇯🇵", subscribers: "100M+", status: "beta" },
  { code: "ko", name: "Korean", flag: "🇰🇷", subscribers: "55M+", status: "beta" },
  { code: "ar", name: "Arabic", flag: "🇸🇦", subscribers: "400M+", status: "soon" },
]

// Thumbnail variants
export const thumbnailVariants = [
  { id: "1", label: "Variant A", ctrScore: 8.4, style: "high-contrast", selected: true },
  { id: "2", label: "Variant B", ctrScore: 7.1, style: "minimal", selected: false },
  { id: "3", label: "Variant C", ctrScore: 6.8, style: "bold-text", selected: false },
  { id: "4", label: "Variant D", ctrScore: 5.9, style: "face-forward", selected: false },
]

// SEO suggestions
export const seoTitles = [
  { title: "I Used AI to Build a $10K YouTube Channel (Step by Step)", score: 94, searchVolume: "High" },
  { title: "10 AI Tools Every YouTuber Needs in 2025", score: 88, searchVolume: "Very High" },
  { title: "How AI Changed My YouTube Strategy Forever", score: 79, searchVolume: "Medium" },
  { title: "The Ultimate AI YouTube Workflow (2025 Guide)", score: 71, searchVolume: "Medium" },
]

// Comment clusters
export const commentClusters = [
  { topic: "Requesting tutorial on setup", count: 847, sentiment: "positive" },
  { topic: "Asking about pricing/tools used", count: 623, sentiment: "neutral" },
  { topic: "Sharing their own results", count: 412, sentiment: "positive" },
  { topic: "Skeptical about income claims", count: 234, sentiment: "negative" },
  { topic: "Requesting Part 2", count: 891, sentiment: "positive" },
]

// Trending topics
export const trendingTopics = [
  { topic: "AI video editing tools 2025", velocity: 94, opportunity: "high", views7d: "12.4M" },
  { topic: "YouTube automation with AI", velocity: 87, opportunity: "high", views7d: "8.1M" },
  { topic: "ChatGPT for content creation", velocity: 71, opportunity: "medium", views7d: "5.6M" },
  { topic: "Faceless YouTube channel", velocity: 68, opportunity: "medium", views7d: "4.2M" },
  { topic: "YouTube Shorts monetization", velocity: 82, opportunity: "high", views7d: "9.8M" },
]

// Brand deals
export const brandDeals = [
  { id: "1", brand: "Notion", logo: "N", rate: "$4,500", status: "negotiating", deliverable: "30s integration", dueDate: "Apr 15", email: "partnerships@notion.so" },
  { id: "2", brand: "Epidemic Sound", logo: "E", rate: "$2,800", status: "active", deliverable: "Dedicated mention", dueDate: "Apr 22", email: "creators@epidemicsound.com" },
  { id: "3", brand: "Skillshare", logo: "S", rate: "$6,000", status: "reviewing", deliverable: "60s mid-roll", dueDate: "May 1", email: "brand@skillshare.com" },
  { id: "4", brand: "NordVPN", logo: "N", rate: "$8,500", status: "inbound", deliverable: "Full integration", dueDate: "TBD", email: "influencer@nordvpn.com" },
  { id: "5", brand: "Hostinger", logo: "H", rate: "$3,200", status: "complete", deliverable: "30s integration", dueDate: "Completed", email: "affiliate@hostinger.com" },
]

// Integrations
export const integrations = [
  { id: "dropbox", name: "Dropbox", description: "Sync raw footage and exports", category: "Storage", connected: true, lastSync: "2 min ago", icon: "dropbox" },
  { id: "gdrive", name: "Google Drive", description: "Access and store project files", category: "Storage", connected: true, lastSync: "5 min ago", icon: "drive" },
  { id: "gmail", name: "Gmail", description: "Manage brand deal emails", category: "Communication", connected: true, lastSync: "Just now", icon: "gmail" },
  { id: "youtube", name: "YouTube Studio", description: "Analytics and publishing", category: "Platform", connected: true, lastSync: "1 min ago", icon: "youtube" },
  { id: "notion", name: "Notion", description: "Content calendar and planning", category: "Productivity", connected: false, lastSync: null, icon: "notion" },
  { id: "slack", name: "Slack", description: "Team notifications and alerts", category: "Communication", connected: false, lastSync: null, icon: "slack" },
  { id: "frameio", name: "Frame.io", description: "Video review and collaboration", category: "Production", connected: false, lastSync: null, icon: "frameio" },
  { id: "stripe", name: "Stripe", description: "Sponsorship invoicing", category: "Finance", connected: false, lastSync: null, icon: "stripe" },
]

// Revenue chart data (12 months)
export const revenueData = [
  { month: "May", adsense: 2100, sponsorship: 0 },
  { month: "Jun", adsense: 2400, sponsorship: 3000 },
  { month: "Jul", adsense: 2800, sponsorship: 0 },
  { month: "Aug", adsense: 3100, sponsorship: 4500 },
  { month: "Sep", adsense: 2900, sponsorship: 2800 },
  { month: "Oct", adsense: 3400, sponsorship: 6000 },
  { month: "Nov", adsense: 4200, sponsorship: 8500 },
  { month: "Dec", adsense: 5100, sponsorship: 4500 },
  { month: "Jan", adsense: 3800, sponsorship: 0 },
  { month: "Feb", adsense: 4400, sponsorship: 6000 },
  { month: "Mar", adsense: 5200, sponsorship: 8500 },
  { month: "Apr", adsense: 4800, sponsorship: 7600 },
]

// Agents
export const agents = [
  {
    id: "research",
    name: "Trend Scout",
    description: "Monitors X/Twitter, Reddit, and YouTube comments to surface trending topics and audience intelligence in your niche.",
    icon: "radar",
    status: "active",
    lastRun: "2 hours ago",
    nextRun: "Mon 8:00 AM",
    reportsGenerated: 47,
    trendsIdentified: 234,
    schedule: "Weekly, Monday 8 AM",
    connectedSources: ["Twitter/X", "YouTube Comments", "Reddit", "News RSS"],
  },
  {
    id: "intel",
    name: "Content Strategist",
    description: "Analyzes your channel performance and generates weekly Brand Briefs with data-backed video ideas tailored to your audience.",
    icon: "lightbulb",
    status: "active",
    lastRun: "1 day ago",
    nextRun: "Mon 9:00 AM",
    reportsGenerated: 23,
    trendsIdentified: 89,
    schedule: "Weekly, Monday 9 AM",
    connectedSources: ["YouTube Analytics", "Trend Scout Output"],
  },
  {
    id: "comms",
    name: "Growth Engine",
    description: "Automates email campaigns, discovers sponsorship leads, and manages outreach so you can focus on creating.",
    icon: "rocket",
    status: "idle",
    lastRun: "3 days ago",
    nextRun: "On demand",
    reportsGenerated: 12,
    trendsIdentified: 64,
    schedule: "On demand",
    connectedSources: ["Gmail", "Subscriber List", "Web Search"],
  },
  {
    id: "publisher",
    name: "Publisher",
    description: "Packages every upload — titles, descriptions, chapters, tags, and a week of social drafts. Pushes to YouTube on your approval.",
    icon: "megaphone",
    status: "active",
    lastRun: "18 min ago",
    nextRun: "On upload",
    reportsGenerated: 12,
    trendsIdentified: 58,
    schedule: "On upload",
    connectedSources: ["YouTube (OAuth)", "Google Docs", "Voice Ref"],
  },
]

// Publisher — package shape
export type PackageStatus = "draft" | "pending" | "pushed"

export type PublisherPackage = {
  id: string
  videoId: string
  videoTitle: string
  status: PackageStatus
  packagedAt: string
  titleVariants: string[]
  description: string
  tags: string[]
  chapters: { time: string; label: string }[]
  pinnedComment: string
  thumbnailIdeas: string[]
  socialKit: {
    tweets: string[]
    threadOutline: string[]
    linkedin: string
    instagram: string
    newsletter: string
  }
}

// Publisher — packaged videos
export const publishedPackages: PublisherPackage[] = [
  {
    id: "p1",
    videoId: "dQw4w9WgXcQ",
    videoTitle: "10 AI Tools That Changed My Workflow Forever",
    status: "pushed",
    packagedAt: "Today, 11:04 AM",
    titleVariants: [
      "10 AI Tools That Changed My Workflow Forever",
      "I Rebuilt My Entire Workflow With AI — 10 Tools That Actually Stuck",
      "After a Year of AI Tools, These 10 Are the Only Ones I Still Use",
      "The 10 AI Tools I Can't Live Without (Creator Workflow 2026)",
    ],
    description: `After a year of testing every AI tool I could find, these are the 10 I actually still use every day — and why the other 40+ are collecting dust.

Chapters:
00:00 Intro — why most AI tools get dropped in a week
01:24 #1 — Scripting (the one that replaced a writer)
04:18 #2 — B-roll generation
07:02 #3 — Thumbnail ideation
09:55 #4 — Voice cleanup
12:30 #5 — Transcription that doesn't suck
15:11 #6–#10 — rapid fire
17:40 The tools I dropped (and why)
18:24 Outro

Tools mentioned: https://links.example/10-ai-tools
Subscribe for a new creator-workflow breakdown every week.`,
    tags: [
      "AI tools",
      "creator workflow",
      "YouTube workflow",
      "AI for YouTubers",
      "best AI tools 2026",
      "content creation",
      "video editing AI",
      "script writing AI",
      "creator productivity",
      "AI tools ranked",
      "YouTube creator tips",
      "faceless channel",
      "AI workflow tutorial",
      "video production AI",
    ],
    chapters: [
      { time: "00:00", label: "Intro — why most AI tools get dropped in a week" },
      { time: "01:24", label: "#1 — Scripting (the one that replaced a writer)" },
      { time: "04:18", label: "#2 — B-roll generation" },
      { time: "07:02", label: "#3 — Thumbnail ideation" },
      { time: "09:55", label: "#4 — Voice cleanup" },
      { time: "12:30", label: "#5 — Transcription that doesn't suck" },
      { time: "15:11", label: "#6–#10 — rapid fire" },
      { time: "17:40", label: "The tools I dropped (and why)" },
    ],
    pinnedComment:
      "Which of the 10 surprised you most? And what's one I missed that you'd add? I'm making a Part 2 of ones I didn't cover.",
    thumbnailIdeas: [
      "10 AI TOOLS — BIG NUMBER, small subtitle ('that actually stuck')",
      "MY WORKFLOW (arrow) AI — split composition with before/after",
      "'I dropped 40 AI tools' — contrarian angle, face forward",
    ],
    socialKit: {
      tweets: [
        "Tested every AI tool I could find for a year.\n\nOnly 10 made it into my daily workflow.\n\nNew video breaks down which ones — and the 40+ I dropped.",
        "The pattern with AI tools that survive my workflow:\n\n— solve one specific pain\n— work offline / don't break\n— cheaper than the human version, not 10× better\n\nLong-form here: [link]",
        "Hot take: most AI 'workflow' tools are solutions looking for a problem.\n\nThe ones I still use a year later? They all replaced something I was already paying a human to do.\n\nFull breakdown ↓",
      ],
      threadOutline: [
        "Hook: 'I tested 50+ AI tools this year. Only 10 stuck. Here's the pattern:'",
        "#1–3: the writing + ideation tools (with screenshots)",
        "#4–6: the video-facing tools",
        "#7–10: the boring ones that saved the most time",
        "The tools I dropped and why (usually: over-promised, under-delivered)",
        "Close: the 1 question I ask before adopting any new tool",
        "CTA: 'full video breaks down the exact stack — link below'",
      ],
      linkedin: `A year ago I started tracking every AI tool I tried, and whether it was still in my workflow 30 days later.

50+ went in. 10 are left.

The pattern isn't what I expected. The tools that survived weren't the shiniest — they were the boring ones that quietly replaced a human expense.

Three that made the cut:
→ Scripting assistant: cut my draft time in half without losing voice
→ Transcript cleanup: turned 45 min of post-production into 5
→ Thumbnail ideation: 20 concepts in the time it took me to write 3

The other 40? Mostly abandoned within a week. Usually because they tried to do too much.

Full breakdown in this week's video (link in comments).`,
      instagram: `Spent a year testing every AI tool I could find.

Only 10 are still in my workflow. The other 40+ got dropped — usually within a week.

New video breaks down exactly which tools survived, and the one question I ask before adding a new one. 🧵 link in bio

#creatoreconomy #youtubecreator #aitools #contentcreator #creatorworkflow`,
      newsletter: `**This week's video: 10 AI Tools That Changed My Workflow Forever**

I've been tracking every AI tool I tried for a year. Out of 50+, only 10 are still in daily use.

The breakdown covers which ones survived, which ones got dropped (and why), and the single filter I now apply before adopting anything new.

[Watch the full video →]`,
    },
  },
  {
    id: "p2",
    videoId: "xYz123Abc9",
    videoTitle: "YouTube Algorithm 2025: What Actually Works",
    status: "pending",
    packagedAt: "Today, 10:22 AM",
    titleVariants: [
      "I Reverse-Engineered the YouTube Algorithm (2025)",
      "The YouTube Algorithm Isn't What You Think in 2026",
      "I Analyzed 500 Videos to Find What the Algorithm Actually Rewards",
      "YouTube Algorithm 2026: The 3 Signals That Actually Matter",
      "Stop Chasing the YouTube Algorithm — Do This Instead",
    ],
    description: `I analyzed 500 of the top-performing videos in my niche over 90 days to figure out what the algorithm is actually rewarding in 2026. The answer wasn't what I expected.

Chapters:
00:00 The myth most creators still believe
02:14 What I tracked across 500 videos
05:40 Signal #1 — the one everyone talks about (and it's half wrong)
09:25 Signal #2 — the silent killer
13:08 Signal #3 — what nobody is optimizing for
16:45 The counterintuitive takeaway
19:30 What I'm changing about my own channel

The full dataset: https://links.example/algo-2026
Part 2 drops next week — subscribe.`,
    tags: [
      "YouTube algorithm 2026",
      "YouTube growth",
      "YouTube strategy",
      "how YouTube works",
      "YouTube ranking",
      "CTR optimization",
      "average view duration",
      "content strategy",
      "YouTube analytics",
      "grow on YouTube",
      "YouTube algorithm explained",
      "creator strategy",
    ],
    chapters: [
      { time: "00:00", label: "The myth most creators still believe" },
      { time: "02:14", label: "What I tracked across 500 videos" },
      { time: "05:40", label: "Signal #1 — and why half of what you've heard is wrong" },
      { time: "09:25", label: "Signal #2 — the silent killer" },
      { time: "13:08", label: "Signal #3 — what nobody is optimizing for" },
      { time: "16:45", label: "The counterintuitive takeaway" },
    ],
    pinnedComment:
      "What's one 'algorithm rule' you've been following that you're now not sure about? Drop it below — if enough people ask I'll test it for Part 2.",
    thumbnailIdeas: [
      "'I analyzed 500 videos' — data-heavy, spreadsheet in background",
      "Algorithm diagram with one signal CIRCLED in red",
      "Face + shocked expression + 'It's not CTR.'",
    ],
    socialKit: {
      tweets: [
        "Spent 90 days analyzing 500 top videos in my niche to figure out what the YouTube algorithm is actually rewarding in 2026.\n\nHalf of what you've heard is wrong.\n\nNew video: [link]",
        "Three signals the YouTube algorithm seems to actually weight in 2026:\n\n1. The one everyone talks about (but not for the reason you think)\n2. A silent killer most creators ignore\n3. Something almost nobody is optimizing for\n\nBreakdown in this week's video.",
        "'CTR is king' is the most overused and under-examined advice in YouTube.\n\nIn my dataset, it wasn't even the strongest predictor of growth.\n\nFull analysis (with the dataset) in the new video.",
      ],
      threadOutline: [
        "Hook: 'I analyzed 500 top videos in my niche. Here's what actually predicts algorithmic lift in 2026:'",
        "Context: the methodology (channels tracked, timeframe, what I measured)",
        "Signal #1: CTR — the nuance everyone misses",
        "Signal #2: the silent killer (session-level behavior)",
        "Signal #3: the overlooked one",
        "The counterintuitive takeaway",
        "CTA: full video has the dataset + breakdown",
      ],
      linkedin: `Most YouTube 'algorithm advice' is folklore.

I spent 90 days analyzing 500 top-performing videos in my niche to see what the algorithm is actually rewarding in 2026. Three signals mattered. Two of them get almost no airtime in creator circles.

The one that surprised me most: a session-level behavior that almost nobody tracks — and that was a stronger predictor of growth than CTR.

Full breakdown + dataset in this week's video.`,
      instagram: `Spent 90 days analyzing 500 videos to answer one question: what does the YouTube algorithm actually reward in 2026?

Half of what you've heard is wrong.

🧵 the 3 signals that actually matter — full video in bio.

#youtubealgorithm #youtubecreator #creatortips #youtubegrowth`,
      newsletter: `**This week: YouTube Algorithm 2026 — What Actually Works**

I analyzed 500 videos over 90 days. Three signals mattered. Two of them almost nobody is talking about.

The counterintuitive one: CTR wasn't even the strongest predictor of growth in my dataset.

Full breakdown + dataset drop in this video.

[Watch →]`,
    },
  },
  {
    id: "p3",
    videoId: "a1B2c3D4e5",
    videoTitle: "I Tried Every AI Video Editor So You Don't Have To",
    status: "pushed",
    packagedAt: "5 days ago",
    titleVariants: [
      "I Tried Every AI Video Editor So You Don't Have To",
      "The AI Video Editor Showdown (2026)",
      "6 AI Video Editors Ranked — Brutal Honesty Edition",
    ],
    description: `I tested 6 major AI video editors on the same 20-minute raw export and ranked them on the stuff that actually matters: cut quality, voice handling, and whether they hallucinate your footage into garbage.

Chapters:
00:00 The only test that matters
02:10 Editor #1
05:22 Editor #2
...`,
    tags: [
      "AI video editor",
      "best AI video editor",
      "Opus Clip",
      "Descript",
      "CapCut AI",
      "Runway",
      "Premiere AI",
      "video editing 2026",
      "AI editing review",
      "automated video editing",
      "AI b-roll",
      "AI cuts",
      "creator tools",
      "video workflow",
      "AI editor comparison",
    ],
    chapters: [
      { time: "00:00", label: "The only test that matters" },
      { time: "02:10", label: "Editor #1" },
      { time: "05:22", label: "Editor #2" },
      { time: "08:40", label: "Editor #3" },
      { time: "12:15", label: "Editor #4" },
      { time: "16:00", label: "Editor #5" },
      { time: "19:30", label: "Editor #6" },
      { time: "22:10", label: "Final ranking" },
    ],
    pinnedComment:
      "Which one did you expect to win? Mine was wrong too. Let me know in the comments — and if you want me to re-test with a specific type of footage, drop the genre.",
    thumbnailIdeas: [
      "6 logos in a grid, one with a green check, rest with red X",
      "Face + 'I tested all 6' + one logo circled",
      "'Only ONE is worth paying for' — contrarian angle",
    ],
    socialKit: {
      tweets: [
        "Tested 6 AI video editors on the same 20-min raw export.\n\nOnly one was actually worth paying for.\n\nFull showdown: [link]",
        "The problem with most 'AI video editor' reviews: they all use pristine footage.\n\nI ran the same messy 20-min talking-head export through all 6. Results were brutal.\n\nNew video ↓",
        "Fun fact: 4 of 6 AI editors I tested hallucinated cuts that weren't in the original footage.\n\nFull video shows the exact examples + which one didn't.",
      ],
      threadOutline: [
        "Hook: '6 AI video editors, 1 raw 20-min export. Only one survived.'",
        "The test methodology",
        "Editor-by-editor rapid verdict",
        "The hallucination problem (with examples)",
        "The winner + why",
        "CTA: full side-by-side in the video",
      ],
      linkedin: `Tested 6 major AI video editors on identical 20 minutes of raw footage. Only one produced something I'd actually publish.

The most uncomfortable finding: 4 out of 6 hallucinated cuts or reordered content in ways the creator wouldn't notice without careful review.

Full comparison (and the one I kept paying for) in this week's video.`,
      instagram: `I put 6 AI video editors through the same raw 20-min export.

Most failed. Some hallucinated cuts. One was actually good.

Full showdown — link in bio.

#aivideo #videoediting #creatortools #aitools`,
      newsletter: `**New video: AI Video Editor Showdown**

Same 20-minute raw export through 6 different AI editors. Only one produced something publishable.

More uncomfortable finding: 4 of 6 quietly hallucinated cuts that weren't in the source.

[Full side-by-side →]`,
    },
  },
  {
    id: "p4",
    videoId: "e5F6g7H8i9",
    videoTitle: "How I Script 30 Videos Per Month with AI",
    status: "draft",
    packagedAt: "Yesterday, 4:15 PM",
    titleVariants: [
      "How I Script 30 Videos Per Month with AI",
      "My AI Scripting Workflow (30 Videos/Month)",
      "The Exact Prompts I Use to Script a Video in 20 Minutes",
      "From Idea to Script in 20 Minutes — My AI Workflow",
      "I Script 30 Videos a Month With AI. Here's the System.",
    ],
    description: `The exact system I use to go from idea to finished script in about 20 minutes — without the output sounding like AI.

Chapters:
00:00 Why most AI scripts sound terrible
...`,
    tags: [
      "AI scripting",
      "video scripting",
      "write YouTube scripts",
      "ChatGPT for YouTube",
      "script workflow",
      "content creation",
      "creator tips",
      "YouTube workflow",
      "scriptwriting AI",
      "faster content",
    ],
    chapters: [
      { time: "00:00", label: "Why most AI scripts sound terrible" },
      { time: "02:30", label: "The 4-step workflow" },
      { time: "06:15", label: "My exact prompts (stealable)" },
      { time: "11:40", label: "The voice-matching trick" },
      { time: "15:20", label: "Where I still write by hand" },
    ],
    pinnedComment:
      "Which part of scripting do you hate the most? I'll cover the worst one in Part 2.",
    thumbnailIdeas: [
      "'30 VIDEOS / MONTH' bold with small 'in 20 min each'",
      "Split: chaotic desk vs calendar full of uploads",
      "Prompt snippet on screen + face forward",
    ],
    socialKit: {
      tweets: [
        "I publish 30 videos a month. I script every one in about 20 minutes with AI.\n\nThe trick isn't the model — it's the 4-step workflow. New video breaks it down with the exact prompts.",
        "The reason most AI scripts sound like AI:\n\nCreators ask it for a 'YouTube script.'\n\nThat's the wrong input.\n\nMy new video shows what to ask instead (with real prompts).",
        "20 minutes from idea to script.\n\n30 scripts a month.\n\n0 of them sounding robotic.\n\nFull workflow + prompts in today's video. ↓",
      ],
      threadOutline: [
        "Hook: '30 videos a month. 20 minutes of scripting each. Here's the system.'",
        "Why most AI scripts sound terrible",
        "Step 1: voice capture (the piece most people skip)",
        "Step 2–4: the actual prompts (pasteable)",
        "Where I still write by hand",
        "CTA: full system in the video",
      ],
      linkedin: `I publish 30 videos a month. Each script takes about 20 minutes.

The hack isn't the model — every time I've experimented with a new LLM, the output quality has been roughly the same. What changed was the workflow.

Four steps. The one most creators skip: capturing your voice before you start prompting.

Full breakdown (with the exact prompts) in this week's video.`,
      instagram: `30 videos a month. 20 minutes per script. Zero robotic-sounding AI output.

The system isn't the model — it's the workflow. Full video breaks it down with the exact prompts.

Link in bio. 🧵

#aiworkflow #contentcreation #creatortips #youtube`,
      newsletter: `**This week: how I script 30 videos a month with AI**

The hack isn't the model. It's a 4-step workflow — and the piece most creators skip.

Full system (with the prompts I actually use) in this video.

[Watch →]`,
    },
  },
]

// Publisher — pending approvals (videos.update interrupts)
export type PendingApproval = {
  id: string
  packageId: string
  videoId: string
  videoTitle: string
  proposedTitle: string
  currentTitle: string
  proposedTagCount: number
  proposedChapterCount: number
  requestedAt: string
}

export const pendingApprovals: PendingApproval[] = [
  {
    id: "a1",
    packageId: "p2",
    videoId: "xYz123Abc9",
    videoTitle: "YouTube Algorithm 2025: What Actually Works",
    proposedTitle: "I Reverse-Engineered the YouTube Algorithm (2025)",
    currentTitle: "final_v3.mp4",
    proposedTagCount: 12,
    proposedChapterCount: 6,
    requestedAt: "15 min ago",
  },
]

// Bot connections
export const botConnections = [
  {
    id: "slack",
    name: "Slack",
    description: "Control all agents with natural language from your Slack workspace. Trigger reports, create tasks, draft emails — all via chat.",
    status: "connected",
    workspace: "KnightShyft AI",
    channel: "#anthracite-bot",
    lastInteraction: "10 min ago",
    commandsAvailable: 30,
    color: "bg-[#4A154B]",
    textColor: "text-[#4A154B]",
    bgLight: "bg-[#4A154B]/10",
    recentCommands: [
      { command: "Run the research report", time: "10 min ago", result: "success" },
      { command: "What's trending in my niche?", time: "1 hr ago", result: "success" },
      { command: "Draft email for today's video", time: "3 hrs ago", result: "success" },
    ],
  },
  {
    id: "discord",
    name: "Discord",
    description: "Add Anthracite to your Discord server for community-facing alerts and private agent control in your mod channels.",
    status: "disconnected",
    workspace: null,
    channel: null,
    lastInteraction: null,
    commandsAvailable: 30,
    color: "bg-[#5865F2]",
    textColor: "text-[#5865F2]",
    bgLight: "bg-[#5865F2]/10",
    recentCommands: [],
  },
  {
    id: "telegram",
    name: "Telegram",
    description: "Get push notifications and trigger agents from Telegram. Perfect for mobile-first creators on the go.",
    status: "disconnected",
    workspace: null,
    channel: null,
    lastInteraction: null,
    commandsAvailable: 18,
    color: "bg-[#2AABEE]",
    textColor: "text-[#2AABEE]",
    bgLight: "bg-[#2AABEE]/10",
    recentCommands: [],
  },
]

// Tasks
export const tasks = [
  { id: "t1", name: "Weekly Research Brief — Apr 7", type: "research", status: "complete", progress: 100, duration: "4m 32s", triggeredBy: "Schedule", output: "PDF Report", outputLabel: "Research_Brief_2026-04-07.pdf", agentId: "research", createdAt: "Today, 8:04 AM" },
  { id: "t2", name: "Weekly Brand Brief — Apr 7", type: "intel", status: "complete", progress: 100, duration: "2m 18s", triggeredBy: "Schedule", output: "PDF Report", outputLabel: "Brand_Brief_2026-04-07.pdf", agentId: "intel", createdAt: "Today, 9:02 AM" },
  { id: "t3", name: "Generate Spanish Dub — 'AI Tools Changed My Workflow'", type: "dubbing", status: "running", progress: 67, duration: "1m 42s", triggeredBy: "User", output: "Audio File", outputLabel: null, agentId: null, createdAt: "Today, 11:30 AM" },
  { id: "t4", name: "Auto-Clip Shorts — 'Passive Income Reality Check'", type: "clips", status: "complete", progress: 100, duration: "5m 11s", triggeredBy: "User", output: "4 Clips", outputLabel: "4 clips ready", agentId: null, createdAt: "Today, 10:15 AM" },
  { id: "t5", name: "Find Sponsorship Leads — Creator Economy niche", type: "comms", status: "running", progress: 23, duration: "0m 34s", triggeredBy: "User", output: "Lead List", outputLabel: null, agentId: "comms", createdAt: "Today, 11:58 AM" },
  { id: "t6", name: "Optimize SEO — 'YouTube Algorithm 2025'", type: "seo", status: "queued", progress: 0, duration: null, triggeredBy: "User", output: "SEO Report", outputLabel: null, agentId: null, createdAt: "Today, 12:01 PM" },
  { id: "t7", name: "Generate Thumbnail Variants — Draft video", type: "thumbnails", status: "failed", progress: 40, duration: "0m 58s", triggeredBy: "User", output: null, outputLabel: "Image extraction failed", agentId: null, createdAt: "Yesterday, 4:22 PM" },
  { id: "t8", name: "Weekly Research Brief — Mar 31", type: "research", status: "complete", progress: 100, duration: "3m 58s", triggeredBy: "Schedule", output: "PDF Report", outputLabel: "Research_Brief_2026-03-31.pdf", agentId: "research", createdAt: "Mar 31, 8:03 AM" },
  { id: "t9", name: "Draft Email — New Video Blast", type: "comms", status: "complete", progress: 100, duration: "0m 12s", triggeredBy: "Slack Bot", output: "Email Draft", outputLabel: "Saved to drafts", agentId: "comms", createdAt: "Yesterday, 2:10 PM" },
  { id: "t10", name: "Subtitle Generation — 'AI Tools Changed My Workflow'", type: "subtitles", status: "complete", progress: 100, duration: "1m 04s", triggeredBy: "User", output: "SRT + VTT", outputLabel: "2 files ready", agentId: null, createdAt: "Yesterday, 9:45 AM" },
]

// Research reports (for agent detail pages)
export const researchReports = [
  { date: "Apr 7, 2026", title: "Weekly Research Brief", size: "1.2 MB", highlights: ["AI video tools trending +340% this week", "Audience asking about passive income follow-up", "2 high-opportunity niche gaps identified"] },
  { date: "Mar 31, 2026", title: "Weekly Research Brief", size: "980 KB", highlights: ["YouTube Shorts monetization dominating discourse", "Creator burnout sentiment rising in comments", "5 competitor channels publishing daily"] },
  { date: "Mar 24, 2026", title: "Weekly Research Brief", size: "1.1 MB", highlights: ["Long-form comeback: 20+ min videos up 22%", "AI dubbing tools becoming mainstream discussion", "Q1 ad rates stronger than expected"] },
]

export const brandBriefs = [
  { date: "Apr 7, 2026", title: "Weekly Brand Brief", size: "890 KB", highlights: ["Top idea: 'AI editor showdown' (high CTR potential)", "Repurpose 'Passive Income' into 3 Shorts", "Engagement rate up 8% vs last month"] },
  { date: "Mar 31, 2026", title: "Weekly Brand Brief", size: "760 KB", highlights: ["Script the burnout video — audience is primed", "Post frequency sweet spot: 2x/week", "Thursday 3 PM is your peak engagement window"] },
]

export const sponsorLeads = [
  { id: "1", company: "Descript", role: "Creator Partnerships", website: "descript.com", status: "New", fit: "High" },
  { id: "2", company: "OpusClip", role: "Influencer Marketing", website: "opus.pro", status: "New", fit: "High" },
  { id: "3", company: "Riverside.fm", role: "Partnerships", website: "riverside.fm", status: "Contacted", fit: "Medium" },
  { id: "4", company: "Beehiiv", role: "Creator Growth", website: "beehiiv.com", status: "New", fit: "Medium" },
]
