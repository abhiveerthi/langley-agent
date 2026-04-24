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
