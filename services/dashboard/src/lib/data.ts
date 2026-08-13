/**
 * Static dummy data for the inner pages (/product, /resources, /solutions).
 *
 * Single source of truth so all 3 pages share the same set of resources,
 * industries, features, and platform stats. Replace with a real API
 * when the backend is ready.
 *
 * Versioning: bump DATA_VERSION when the shape changes so consumers
 * (and tests) can detect mismatches.
 */
export const DATA_VERSION = "1.0.0";

/* ─────────────────  Solutions — industries  ───────────────── */
export const INDUSTRIES = [
  {
    title: "Manufacturing",
    image: "/images/industry-1.webp",
    alt: "Manufacturing plant",
    href: "/solutions/manufacturing",
    body: "Track and reduce emissions across production lines and supply chains.",
    metrics: { emissions: "1.2M tCO₂e", reduction: "32%", sites: 24 },
  },
  {
    title: "Energy & Utilities",
    image: "/images/industry-2.webp",
    alt: "Wind turbines",
    href: "/solutions/energy",
    body: "Optimize energy generation and grid operations with real-time data.",
    metrics: { emissions: "850K tCO₂e", reduction: "41%", sites: 18 },
  },
  {
    title: "Transportation & Logistics",
    image: "/images/industry-3.webp",
    alt: "Trucks at depot",
    href: "/solutions/transport",
    body: "Measure fleet emissions and plan low-carbon routes.",
    metrics: { emissions: "640K tCO₂e", reduction: "24%", sites: 12 },
  },
  {
    title: "Construction & Real Estate",
    image: "/images/industry-4.webp",
    alt: "Construction site",
    href: "/solutions/construction",
    body: "Track embodied carbon and operational emissions for buildings.",
    metrics: { emissions: "320K tCO₂e", reduction: "19%", sites: 9 },
  },
  {
    title: "Technology & SaaS",
    image: "/images/industry-5.webp",
    alt: "Server room",
    href: "/solutions/tech",
    body: "Scope 3 emissions and cloud carbon footprint management.",
    metrics: { emissions: "180K tCO₂e", reduction: "37%", sites: 6 },
  },
] as const;

/* ─────────────────  Solutions — platform features  ───────────────── */
export const PLATFORM_FEATURES = [
  {
    title: "AI-Driven Insights",
    body: "Real-time analytics and predictive insights for sustainable impact.",
    icon: "brain",
  },
  {
    title: "Unified Data Hub",
    body: "All your data, integrated for a complete view of impact.",
    icon: "hub",
  },
  {
    title: "Custom Workflows",
    body: "Tailor the platform to your unique business needs.",
    icon: "flow",
  },
  {
    title: "Enterprise Security",
    body: "SOC 2, ISO 27001, and GDPR compliant infrastructure.",
    icon: "shield",
  },
  {
    title: "Scalable Architecture",
    body: "Built to grow with your business, from SMB to Enterprise.",
    icon: "scale",
  },
  {
    title: "Global Coverage",
    body: "Country-specific regulations and emission factors built in.",
    icon: "globe",
  },
] as const;

export const SOLUTIONS_STATS = [
  { value: 2400000, suffix: "+ tCO₂e", label: "Measured", icon: "cloud" },
  { value: 28, suffix: "%", label: "Average Reduction", icon: "trend" },
  { value: 75, suffix: "+", label: "Countries", icon: "globe" },
  { value: 1250, suffix: "+", label: "Organizations", icon: "group" },
] as const;

/* ─────────────────  Product — features  ───────────────── */
export const PRODUCT_FEATURES = [
  {
    title: "Smart Data Ingestion",
    body: "Connect all your data sources in minutes. We handle the complexity.",
    bullets: ["ERP, IoT, Utility, Cloud & more", "Automated data validation", "Real-time or scheduled sync"],
    icon: "cloud",
    visual: "funnel",
  },
  {
    title: "AI-Powered Calculations",
    body: "Industry-leading models and AI ensure accuracy and transparency.",
    bullets: ["Multiple methodologies", "AI anomaly detection", "What-if scenario modeling"],
    icon: "brain",
    visual: "brain",
  },
  {
    title: "Actionable Insights",
    body: "Go beyond numbers. Get insights that help you act and improve.",
    bullets: ["Hotspot identification", "Reduction opportunities", "Benchmarks & comparisons"],
    icon: "chart",
    visual: "chart",
  },
  {
    title: "Goals & Tracking",
    body: "Set science-based goals and track progress in real time.",
    bullets: ["SBTi aligned goals", "Real-time progress tracking", "Milestone & alerts"],
    icon: "target",
    visual: "donut",
  },
  {
    title: "Reports & Compliance",
    body: "Generate audit-ready reports aligned with global standards.",
    bullets: ["GRI, CDP, TCFD, CSRD", "Custom report builder", "One-click export"],
    icon: "doc",
    visual: "report",
  },
  {
    title: "Reduce & Offset",
    body: "Take action and neutralize your unavoidable emissions.",
    bullets: ["Reduction planning", "Offset marketplace", "Impact verification"],
    icon: "leaf",
    visual: "wind",
  },
] as const;

export const PRODUCT_STEPS = [
  { number: 1, title: "Connect", body: "Integrate your data sources securely.", icon: "cloud" },
  { number: 2, title: "Measure", body: "We calculate your emissions accurately.", icon: "doc" },
  { number: 3, title: "Act", body: "Get insights and take meaningful actions.", icon: "leaf" },
  { number: 4, title: "Impact", body: "Track progress and drive lasting change.", icon: "globe" },
] as const;

export const PRODUCT_PILL_FEATURES = [
  { title: "Accurate", body: "Science-backed models for reliable carbon accounting.", icon: "accurate" },
  { title: "Actionable", body: "Turn insights into real world sustainability actions.", icon: "action" },
  { title: "Transparent", body: "Clear, audit-ready reports you can trust.", icon: "trans" },
] as const;

/* ─────────────────  Resources  ───────────────── */
export const CATEGORIES = [
  { title: "Guides & Playbooks", body: "Step-by-step guides to help you on your sustainability journey.", resourceCount: 135, href: "/resources/guides", icon: "book" },
  { title: "Reports & Research", body: "In-depth research, market reports, and industry benchmarks.", resourceCount: 98, href: "/resources/reports", icon: "chart" },
  { title: "Tools & Calculators", body: "Practical tools to measure, calculate, and analyze your impact.", resourceCount: 40, href: "/resources/tools", icon: "tool" },
  { title: "Videos & Webinars", body: "Watch expert sessions and on-demand webinars.", resourceCount: 75, href: "/resources/videos", icon: "video" },
  { title: "Case Studies", body: "Real-world success stories from organizations driving change.", resourceCount: 60, href: "/resources/cases", icon: "case" },
  { title: "Policy & Standards", body: "Stay up to date with global frameworks and regulations.", resourceCount: 65, href: "/resources/policy", icon: "shield" },
] as const;

export const FEATURED_RESOURCES = [
  { type: "GUIDE", title: "Carbon Accounting 101", body: "A beginner's guide to measuring and reporting greenhouse gas emissions.", meta: "15 min read", level: "Beginner", image: "/images/resource-1.webp", alt: "Wind turbines against a sunset", href: "/resources/carbon-101" },
  { type: "TEMPLATE", title: "GHG Inventory Template", body: "Streamline your data collection and emissions calculation.", meta: "Excel Template", level: "Intermediate", image: "/images/resource-2.webp", alt: "Laptop with dashboards", href: "/resources/ghg-template" },
  { type: "REPORT", title: "State of Corporate Sustainability 2024", body: "Key trends, data, and insights shaping the sustainability landscape.", meta: "25 min read", level: "Report", image: "/images/resource-3.webp", alt: "Aerial forest", href: "/resources/sos-2024" },
  { type: "WEBINAR", title: "Net Zero Roadmap", body: "Watch experts discuss actionable strategies for net zero.", meta: "45 min", level: "Advanced", image: "/images/resource-4.webp", alt: "Webinar session", href: "/resources/net-zero-webinar" },
  { type: "CASE STUDY", title: "How GreenTech Cut Emissions by 40%", body: "A case study on data-driven decisions and real impact.", meta: "12 min read", level: "Case Study", image: "/images/resource-5.webp", alt: "Green building", href: "/resources/greentech-case" },
] as const;

export const TOOLS = [
  { title: "Carbon Footprint Calculator", body: "Estimate your organization's emissions in minutes.", cta: "Use Calculator", icon: "calc" },
  { title: "Emissions Factor Database", body: "Access 10,000+ emission factors across industries.", cta: "Explore Database", icon: "db" },
  { title: "ESG Report Template", body: "Create investor-ready ESG reports with ease.", cta: "Download Template", icon: "doc" },
  { title: "Science-Based Targets Guide", body: "Step-by-step guide to set and achieve SBTs.", cta: "Read Guide", icon: "target" },
] as const;

export const RESOURCE_STATS = [
  { value: 1200, suffix: "+", label: "Resources", icon: "book" },
  { value: 85, suffix: "+", label: "Expert Contributors", icon: "person" },
  { value: 50000, suffix: "+", label: "Active Learners", icon: "group" },
  { value: 120, suffix: "+", label: "Countries Reached", icon: "globe" },
] as const;

export const POPULAR_TAGS = ["Carbon Accounting 101", "GHG Protocol", "Emissions Factors", "ESG Reporting", "Net Zero Guide"] as const;

/* ════════════════════════════════════════════════════════════
   DASHBOARD DATA
   ════════════════════════════════════════════════════════════
   Static data for /dashboard/* pages. All numeric values are
   demo / dummy — replace with API when backend is ready. */

/* ─────────────────  /dashboard/home (Overview)  ───────────────── */
export const HOME_KPIS = [
  { id: "total", label: "Total Emissions", value: "2,453", unit: "tCO₂e", trend: { direction: "down" as const, text: "18% vs last month", goodWhen: "down" as const } },
  { id: "intensity", label: "Emission Intensity", value: "0.42", unit: "tCO₂e / $K", trend: { direction: "down" as const, text: "12% vs last month", goodWhen: "down" as const } },
  { id: "cost", label: "Total Cost", value: "$128,430", trend: { direction: "down" as const, text: "9% vs last month", goodWhen: "down" as const } },
  { id: "reduction", label: "Reduction vs Baseline", value: "28%", sub: "On track for 2030 goal", trend: { direction: "up" as const, text: "vs baseline", goodWhen: "up" as const } },
  { id: "forecast", label: "Forecasted (2024)", value: "28,650", unit: "tCO₂e", sub: "vs 2023 forecast", trend: { direction: "down" as const, text: "14% vs 2023", goodWhen: "down" as const } },
] as const;

export const HOME_SCOPES = [
  { label: "Scope 1", value: 613, percent: 25, color: "rgba(132,204,22,0.95)" },
  { label: "Scope 2", value: 1104, percent: 45, color: "rgba(16,185,129,0.95)" },
  { label: "Scope 3", value: 736, percent: 30, color: "rgba(168,85,247,0.95)" },
] as const;

export const HOME_EMISSIONS_TREND = {
  labels: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
  current: [1850, 1920, 2050, 2180, 2300, 2400, 2350, 2420, 2380, 2450, 2453, 2400],
  baseline: [2200, 2250, 2300, 2350, 2400, 2450, 2480, 2500, 2520, 2540, 2550, 2560],
};

/* ─────────────────  /dashboard/actions  ───────────────── */
export const ACTIONS_KPIS = [
  { id: "potential", label: "Potential Reduction", value: "1,246", unit: "tCO₂e", sub: "31% of total emissions" },
  { id: "savings", label: "Potential Cost Savings", value: "$420K", sub: "Annual savings" },
  { id: "in-progress", label: "Implementation in Progress", value: "5", sub: "Actions started" },
  { id: "completed", label: "Completed Actions", value: "8", sub: "This year" },
  { id: "roi", label: "Avg. ROI", value: "2.8x", sub: "Across all actions" },
] as const;

export const ACTION_RECOMMENDATIONS = [
  { id: 1, title: "Switch to Renewable Energy", category: "Energy", body: "Transition to 100% renewable electricity through green energy tariffs.", reduction: 320, cost: "$45,000/yr", difficulty: "Medium", roi: "3.4x", priority: "High", status: "Recommended", effort: 3 },
  { id: 2, title: "Optimize Logistics Routes", category: "Logistics", body: "Use AI route optimization and consolidate shipments to reduce fuel consumption.", reduction: 180, cost: "$18,000/yr", difficulty: "Low", roi: "2.7x", priority: "High", status: "Recommended", effort: 2 },
  { id: 3, title: "Reduce High-Emission Suppliers", category: "Supply Chain", body: "Engage suppliers and switch to low-carbon alternatives.", reduction: 250, cost: "$25,000/yr", difficulty: "High", roi: "2.1x", priority: "Medium", status: "Recommended", effort: 4 },
  { id: 4, title: "Improve Energy Efficiency", category: "Operations", body: "Upgrade to energy-efficient equipment and smart building controls.", reduction: 140, cost: "$75,000", difficulty: "Medium", roi: "3.9x", priority: "Medium", status: "In Progress", effort: 3 },
  { id: 5, title: "Reduce Business Travel Emissions", category: "Travel", body: "Encourage virtual meetings and optimize travel policies.", reduction: 90, cost: "$8,000/yr", difficulty: "Low", roi: "4.2x", priority: "Medium", status: "Not Started", effort: 2 },
  { id: 6, title: "Reduce Waste & Increase Recycling", category: "Waste", body: "Implement waste reduction programs and improve recycling rates.", reduction: 60, cost: "$5,000/yr", difficulty: "Low", roi: "1.8x", priority: "Low", status: "Not Started", effort: 1 },
] as const;

export const ACTION_CATEGORIES_BREAKDOWN = [
  { label: "Energy",       reduction: 520, percent: 42 },
  { label: "Supply Chain", reduction: 250, percent: 20 },
  { label: "Logistics",    reduction: 180, percent: 14 },
  { label: "Operations",   reduction: 140, percent: 11 },
  { label: "Travel",       reduction: 90,  percent: 7 },
] as const;

export const ACTION_OVERVIEW = {
  total: 12,
  recommended: 5,
  inProgress: 3,
  notStarted: 3,
  completed: 1,
} as const;

export const ROADMAP = [
  { phase: "Short Term (0–3 months)", items: ["Optimize logistics", "Reduce business travel", "Improve recycling"] },
  { phase: "Mid Term (3–12 months)",  items: ["Improve energy efficiency", "Supplier engagement"] },
  { phase: "Long Term (12+ months)",  items: ["Switch to renewable energy", "Process innovation"] },
] as const;

/* ─────────────────  /dashboard/analytics  ───────────────── */
export const ANALYTICS_KPIS = [
  { id: "total", label: "Total Emissions", value: "2,453", unit: "tCO₂e", trend: { direction: "down" as const, text: "18% vs last month", goodWhen: "down" as const } },
  { id: "intensity", label: "Emissions Intensity", value: "0.42", unit: "tCO₂e / $K", trend: { direction: "down" as const, text: "12% vs last month", goodWhen: "down" as const } },
  { id: "cost", label: "Total Cost", value: "$128,430", trend: { direction: "down" as const, text: "9% vs last month", goodWhen: "down" as const } },
  { id: "reduction", label: "Reduction vs Baseline", value: "28%", sub: "On track for 2030 goal" },
  { id: "forecast", label: "Forecasted (2024)", value: "28,650", unit: "tCO₂e", sub: "vs 2023 forecast", trend: { direction: "down" as const, text: "14% vs 2023", goodWhen: "down" as const } },
] as const;

export const ANALYTICS_SCOPES = [
  { label: "Scope 1", value: 613, percent: 25, color: "rgba(132,204,22,0.95)" },
  { label: "Scope 2", value: 1104, percent: 45, color: "rgba(56,189,248,0.95)" },
  { label: "Scope 3", value: 736, percent: 30, color: "rgba(168,85,247,0.95)" },
] as const;

export const ANALYTICS_TREND = {
  labels: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
  current: [1850, 1920, 2050, 2180, 2300, 2400, 2350, 2420, 2380, 2450, 2453, 2400],
  baseline: [2200, 2250, 2300, 2350, 2400, 2450, 2480, 2500, 2520, 2540, 2550, 2560],
};

export const ANALYTICS_INDUSTRY = [
  { label: "You",            value: 0.42 },
  { label: "Construction",   value: 0.73 },
  { label: "Manufacturing",  value: 0.58 },
  { label: "Energy",         value: 0.24 },
  { label: "Technology",     value: 0.91 },
  { label: "Services",       value: 0.36 },
] as const;

export const ANALYTICS_OPPORTUNITIES = [
  { id: 1, name: "Switch to Renewable Energy",  reduction: 512, percent: 21, cost: "$$", effort: "Medium", roi: "3.4x", priority: "High" },
  { id: 2, name: "Optimize Logistics Routes",  reduction: 312, percent: 13, cost: "$",  effort: "Low",    roi: "2.7x", priority: "High" },
  { id: 3, name: "Reduce High-Emission Suppliers", reduction: 245, percent: 10, cost: "$$", effort: "High", roi: "2.1x", priority: "Medium" },
  { id: 4, name: "Improve Energy Efficiency",  reduction: 198, percent: 8,  cost: "$$", effort: "Medium", roi: "2.9x", priority: "Medium" },
  { id: 5, name: "Reduce Business Travel",     reduction: 126, percent: 5,  cost: "$",  effort: "Low",    roi: "1.8x", priority: "Low" },
] as const;

/* ─────────────────  /dashboard/goals  ───────────────── */
export const GOALS_KPIS = [
  { id: "active", label: "Active Goals", value: "6", sub: "1 new this month" },
  { id: "target", label: "Total Target Reduction", value: "42%", sub: "By 2030" },
  { id: "emissions", label: "Emissions to Reduce", value: "1,250", unit: "tCO₂e", sub: "From 2023 baseline" },
  { id: "progress", label: "Avg Progress", value: "58%", sub: "Across all goals" },
  { id: "on-track", label: "On Track", value: "4/6", sub: "67% of goals" },
] as const;

export const GOAL_ROADMAP_DATA = {
  labels: ["2023", "2024", "2025", "2026", "2027", "2028", "2029", "2030"],
  actual:    [2976, 2730, 2453, 2200, 1900, 1500, 1100, 700],
  target:    [2976, 2650, 2350, 2050, 1750, 1450, 1150, 850],
  baseline:  [2976, 2976, 2976, 2976, 2976, 2976, 2976, 2976],
};

export const YOUR_GOALS = [
  { id: 1, name: "Net Zero by 2030", sub: "Company-wide", type: "Net Zero", target: "Net Zero by 2030", progress: 58, status: "On Track", deadline: "Dec 31, 2030" },
  { id: 2, name: "Reduce 42% Scope 1 & 2", sub: "Absolute reduction", type: "SBTi", target: "42% by 2030", progress: 61, status: "On Track", deadline: "Dec 31, 2030" },
  { id: 3, name: "Reduce 25% Scope 3", sub: "Absolute reduction", type: "SBTi", target: "25% by 2030", progress: 33, status: "At Risk", deadline: "Dec 31, 2030" },
  { id: 4, name: "50% Renewable Energy", sub: "Energy Transition", type: "Other", target: "50% by 2026", progress: 76, status: "On Track", deadline: "Jun 30, 2026" },
  { id: 5, name: "Reduce 20% Scope 1 & 2", sub: "Short-term target", type: "SBTi", target: "20% by 2025", progress: 82, status: "On Track", deadline: "Dec 31, 2025" },
  { id: 6, name: "Supplier Engagement", sub: "Engage key suppliers", type: "Other", target: "80% by 2026", progress: 40, status: "Behind", deadline: "Jun 30, 2026" },
] as const;

export const GOAL_TYPES = [
  { label: "SBTi Targets",    value: 3, percent: 50, color: "rgba(132,204,22,0.95)" },
  { label: "Net-zero Targets", value: 2, percent: 33, color: "rgba(56,189,248,0.95)" },
  { label: "Other Targets",    value: 1, percent: 17, color: "rgba(168,85,247,0.95)" },
] as const;

export const UPCOMING_DEADLINES = [
  { id: 1, name: "Reduce 20% Scope 1 & 2", date: "Dec 31, 2025", daysLeft: 164 },
  { id: 2, name: "50% Renewable Energy",   date: "Jun 30, 2026", daysLeft: 345 },
  { id: 3, name: "Net Zero Commitment",     date: "Dec 31, 2030", daysLeft: 2001 },
] as const;

export const MILESTONES = [
  { id: 1, name: "Baseline Assessment",    status: "Completed", date: "Mar 15, 2023" },
  { id: 2, name: "Set Science-Based Targets", status: "Completed", date: "May 10, 2023" },
  { id: 3, name: "Reduce 20% Scope 1 & 2",  status: "On Track", date: "Dec 31, 2025" },
  { id: 4, name: "50% Renewable Energy",   status: "Upcoming", date: "Jun 30, 2026" },
  { id: 5, name: "Net Zero Achieved",      status: "Upcoming", date: "Dec 31, 2030" },
] as const;

/* ─────────────────  /dashboard/sources  ───────────────── */
export const SOURCES_KPIS = [
  { id: "total", label: "Total Data Sources", value: "11", sub: "3 new this month" },
  { id: "active", label: "Active Sources", value: "8", sub: "72.7% of total" },
  { id: "points", label: "Data Points", value: "2.4M", sub: "15% vs last month" },
  { id: "emissions", label: "Total Emissions", value: "2,453", unit: "tCO₂e", sub: "18% vs last month" },
  { id: "freshness", label: "Data Freshness", value: "98%", sub: "Excellent" },
] as const;

export const DATA_SOURCES = [
  { id: 1, name: "AWS CloudTrail",   sub: "Amazon Web Services", type: "Cloud",   status: "Active",  lastSync: "2 min ago",   dataPoints: 245320, emissions: 512.45, freshness: 98 },
  { id: 2, name: "Stripe Payments",  sub: "Payment Processor",  type: "Finance", status: "Active",  lastSync: "15 min ago",  dataPoints: 85430,  emissions: 120.38, freshness: 96 },
  { id: 3, name: "Fleet GPS Data",   sub: "Transportation",     type: "Logistics", status: "Active",  lastSync: "32 min ago",  dataPoints: 532184, emissions: 856.72, freshness: 97 },
  { id: 4, name: "Electricity Usage",sub: "Energy Provider",    type: "Energy",   status: "Active",  lastSync: "1 hour ago",  dataPoints: 128645, emissions: 342.18, freshness: 99 },
  { id: 5, name: "Waste Management", sub: "Waste Management",   type: "Waste",    status: "Active",  lastSync: "2 hours ago", dataPoints: 42184,  emissions: 68.43,  freshness: 95 },
  { id: 6, name: "Water Consumption",sub: "Water Utility",      type: "Utilities", status: "Active",  lastSync: "3 hours ago", dataPoints: 23876,  emissions: 24.18,  freshness: 94 },
  { id: 7, name: "Google Workspace", sub: "Productivity Suite", type: "SaaS",     status: "Active",  lastSync: "5 hours ago", dataPoints: 76432,  emissions: 45.12,  freshness: 93 },
  { id: 8, name: "MongoDB Atlas",    sub: "Database",           type: "Cloud",   status: "Inactive", lastSync: "1 day ago",   dataPoints: 12430,  emissions: 12.65,  freshness: 0 },
  { id: 9, name: "Manual Uploads",    sub: "Custom Data",        type: "Manual",   status: "Active",  lastSync: "2 days ago",  dataPoints: 8765,   emissions: 9.12,   freshness: 90 },
  { id: 10, name: "Supplier Data Feed", sub: "Supply Chain",      type: "Supply Chain", status: "Syncing", lastSync: "Syncing…", dataPoints: 0, emissions: 0, freshness: 0 },
  { id: 11, name: "SAP ERP",          sub: "Enterprise Resource Planning", type: "ERP", status: "Inactive", lastSync: "3 days ago", dataPoints: 0, emissions: 0, freshness: 0 },
] as const;

export const SOURCE_HEALTH = { healthy: 8, syncing: 1, inactive: 2, percent: 98 } as const;

export const SOURCES_BY_TYPE = [
  { label: "Cloud",      value: 3, percent: 27, color: "rgba(56,189,248,0.95)" },
  { label: "Energy",     value: 2, percent: 18, color: "rgba(132,204,22,0.95)" },
  { label: "Finance",    value: 2, percent: 18, color: "rgba(168,85,247,0.95)" },
  { label: "Logistics",  value: 2, percent: 18, color: "rgba(16,185,129,0.95)" },
  { label: "SaaS",       value: 1, percent: 9,  color: "rgba(244,63,94,0.95)" },
  { label: "Others",     value: 1, percent: 10, color: "rgba(148,163,184,0.6)" },
] as const;

export const SOURCE_BREAKDOWN = [
  { label: "Fleet GPS Data",  value: 856.72, percent: 34.9 },
  { label: "AWS CloudTrail",  value: 512.45, percent: 20.9 },
  { label: "Electricity Usage", value: 342.18, percent: 14.0 },
  { label: "Stripe Payments", value: 120.38, percent: 4.9 },
  { label: "Waste Management", value: 68.43, percent: 2.8 },
  { label: "Others",          value: 552.84, percent: 22.5 },
] as const;

export const SOURCE_ALERTS = [
  { id: 1, name: "MongoDB Atlas",   time: "1 day ago",   type: "Connection failed" },
  { id: 2, name: "Supplier Data Feed", time: "2 hours ago", type: "Sync delayed" },
  { id: 3, name: "Electricity Usage", time: "3 hours ago", type: "Data validated" },
] as const;

export const POPULAR_INTEGRATIONS = [
  { id: 1, name: "AWS",             sub: "Cloud", color: "#FF9900" },
  { id: 2, name: "Google Cloud",    sub: "Cloud", color: "#4285F4" },
  { id: 3, name: "Microsoft Azure", sub: "Cloud", color: "#00A4EF" },
  { id: 4, name: "Stripe",          sub: "Finance", color: "#635BFF" },
  { id: 5, name: "Salesforce",      sub: "CRM", color: "#00A1E0" },
  { id: 6, name: "SAP",             sub: "ERP", color: "#0FAAFF" },
] as const;

/* ─────────────────  /dashboard/notifications  ───────────────── */
export const NOTIFICATIONS_KPIS = [
  { id: "unread", label: "Unread", value: "6", sub: "View all unread" },
  { id: "today", label: "Today", value: "12", sub: "20% vs yesterday" },
  { id: "week", label: "This Week", value: "38", sub: "15% vs last week" },
  { id: "critical", label: "Critical", value: "2", sub: "Requires immediate attention" },
  { id: "resolved", label: "Resolved", value: "24", sub: "In the last 7 days" },
] as const;

export const NOTIFICATION_LIST = [
  { id: 1, title: "New Recommendation Available", body: "AI has generated 3 new recommendations to help reduce emissions.", type: "Recommendation", priority: "Medium", time: "10 min ago", color: "blue" },
  { id: 2, title: "Goal Milestone Achieved", body: "Great job! You've achieved 50% progress towards Reduce Scope 1 & 2 emissions by 2030.", type: "Goal", priority: "Low", time: "1 hour ago", color: "emerald" },
  { id: 3, title: "Data Ingestion Failure", body: "Failed to ingest data from \"Electricity - Dhaka Office\". Please check the connection and try again.", type: "Data", priority: "High", time: "2 hours ago", color: "rose" },
  { id: 4, title: "Report Generation Completed", body: "Your report \"GHG Protocol Report - Q1 2024\" has been generated successfully.", type: "Report", priority: "Low", time: "3 hours ago", color: "purple" },
  { id: 5, title: "Emission Anomaly Detected", body: "An unusual increase of 35% detected in Transportation emissions compared to last month.", type: "Anomaly", priority: "High", time: "5 hours ago", color: "amber" },
  { id: 6, title: "Compliance Deadline Approaching", body: "CDP Climate Change responses deadline is in 10 days (May 25, 2024).", type: "Compliance", priority: "Medium", time: "6 hours ago", color: "sky" },
  { id: 7, title: "Data Ingestion Successful", body: "Data from \"Natural Gas - Plant 2\" was ingested successfully.", type: "Data", priority: "Low", time: "8 hours ago", color: "emerald" },
  { id: 8, title: "You were mentioned", body: "Sarah Ahmed mentioned you in a comment on \"Net Zero 2040 Goal\".", type: "Mention", priority: "Low", time: "Yesterday, 09:15 PM", color: "purple" },
  { id: 9, title: "Recommendation Implemented", body: "Your recommendation \"Switch to LED Lighting\" has been marked as Implemented.", type: "Recommendation", priority: "Low", time: "Yesterday, 04:30 PM", color: "blue" },
  { id: 10, title: "Data Quality Issue", body: "Data quality check failed for \"Supplier Emissions\". Missing 12 required records.", type: "Data", priority: "High", time: "May 11, 2024 11:20 AM", color: "rose" },
] as const;

export const NOTIFICATION_TYPES_BREAKDOWN = [
  { label: "Recommendations", value: 8, percent: 21, color: "rgba(56,189,248,0.95)" },
  { label: "Goals",            value: 7, percent: 18, color: "rgba(16,185,129,0.95)" },
  { label: "Data",             value: 9, percent: 24, color: "rgba(244,63,94,0.95)" },
  { label: "Reports",          value: 5, percent: 13, color: "rgba(168,85,247,0.95)" },
  { label: "Anomalies",        value: 4, percent: 11, color: "rgba(245,158,11,0.95)" },
  { label: "Compliance",       value: 5, percent: 13, color: "rgba(132,204,22,0.95)" },
] as const;

export const NOTIFICATION_CHANNELS = [
  { label: "In-app", enabled: true },
  { label: "Email",  enabled: true },
  { label: "SMS",    enabled: false },
  { label: "Slack",  enabled: true },
] as const;

/* ─────────────────  /dashboard/organization  ───────────────── */
export const ORG_OVERVIEW = {
  name: "EcoLens Technologies Ltd.",
  verified: true,
  industry: "Software & IT Services",
  founded: "Jan 15, 2020",
  hq: "Dhaka, Bangladesh",
  orgId: "org_867b2c1e",
  employees: 482,
  growth: 12,
  locations: 8,
  facilities: 14,
  fiscalYear: "Jan – Dec",
  framework: "GHG Protocol",
} as const;

export const ORG_LOCATIONS = [
  { id: 1, name: "Dhaka, Bangladesh",  type: "Headquarters",   employees: 268, flag: "🇧🇩" },
  { id: 2, name: "Singapore, Singapore", type: "Regional Office", employees: 84, flag: "🇸🇬" },
  { id: 3, name: "New York, USA",       type: "Office",          employees: 56, flag: "🇺🇸" },
  { id: 4, name: "London, UK",          type: "Office",          employees: 32, flag: "🇬🇧" },
  { id: 5, name: "Berlin, Germany",     type: "Office",          employees: 24, flag: "🇩🇪" },
] as const;

export const ORG_FACILITIES = [
  { id: 1, name: "Corporate HQ Building", location: "Dhaka, Bangladesh",    area: "25,000 ft²" },
  { id: 2, name: "Data Center 1",          location: "Singapore, Singapore", area: "12,500 ft²" },
  { id: 3, name: "Office Building – NY",   location: "New York, USA",        area: "8,200 ft²" },
  { id: 4, name: "Logistics Warehouse",    location: "Berlin, Germany",      area: "18,000 ft²" },
] as const;

export const ORG_EMPLOYEES = {
  total: 482,
  breakdown: [
    { label: "Full-time", value: 352, percent: 73, color: "rgba(132,204,22,0.95)" },
    { label: "Part-time", value: 48,  percent: 10, color: "rgba(168,85,247,0.95)" },
    { label: "Contractor",value: 56,  percent: 12, color: "rgba(56,189,248,0.95)" },
    { label: "Intern",   value: 26,  percent: 5,  color: "rgba(244,63,94,0.95)" },
  ],
} as const;

export const ORG_FRAMEWORKS = [
  { id: 1, name: "GHG Protocol", sub: "Corporate Standard", primary: true,  role: "Primary" },
  { id: 2, name: "TCFD",         sub: "Task Force on Climate-related Financial Disclosures", primary: false, role: "Secondary" },
  { id: 3, name: "SASB",         sub: "Sustainability Accounting Standards Board", primary: false, role: "Secondary" },
  { id: 4, name: "GRI",          sub: "Global Reporting Initiative", primary: false, role: "Supporting" },
  { id: 5, name: "CDP",          sub: "Carbon Disclosure Project", primary: false, role: "Supporting" },
] as const;

/* ─────────────────  /dashboard/profile  ───────────────── */
export const PROFILE_USER = {
  name: "Diptu Alam",
  role: "Administrator",
  email: "diptu@ecolens.com",
  department: "Sustainability",
  location: "Dhaka, Bangladesh",
  memberSince: "Jan 12, 2024",
  lastLogin: "May 12, 2024, 09:30 AM",
  jobTitle: "Sustainability Manager",
  phone: "+880 1712 345678",
  language: "English (US)",
  bio: "Sustainability Leader passionate about data-driven climate action.",
} as const;

export const PROFILE_PREFERENCES = [
  { id: "theme",    label: "Theme",          value: "Dark",           hint: "Choose your preferred theme" },
  { id: "date",     label: "Date Format",    value: "May 12, 2024 (MM DD, YYYY)", hint: "Choose how dates are displayed" },
  { id: "tz",       label: "Time Zone",      value: "(GMT+06:00) Asia/Dhaka", hint: "Select your current time zone" },
  { id: "dash",     label: "Default Dashboard", value: "Overview",   hint: "Choose your default landing page" },
  { id: "units",    label: "Units & Currency", value: "Metric (kg, tCO₂e) & USD", hint: "Set your preferred units and currency" },
  { id: "number",   label: "Number Format",  value: "1,234.56",       hint: "Choose your number format" },
] as const;

export const PROFILE_NOTIFICATION_CATEGORIES = [
  { id: "recs",       label: "Recommendations", body: "New AI-powered recommendations and improvement opportunities" },
  { id: "goals",      label: "Goal Milestones",  body: "Updates on goal progress and milestone achievements" },
  { id: "alerts",     label: "Data & System Alerts", body: "Data ingestion issues, system failures, and anomalies" },
  { id: "reports",    label: "Reports",          body: "Report generation completed and ready to download" },
  { id: "compliance", label: "Compliance & Deadlines", body: "Upcoming deadlines and compliance notifications" },
  { id: "product",    label: "Product Updates",  body: "New features, product updates, and announcements" },
] as const;

/* ─────────────────  /dashboard/reports  ───────────────── */
export const REPORTS_KPIS = [
  { id: "generated", label: "Reports Generated", value: "28", sub: "33% vs last year" },
  { id: "total", label: "Total Reports", value: "42", sub: "All time" },
  { id: "downloads", label: "Downloads", value: "156", sub: "21% vs last year" },
  { id: "last", label: "Last Report", value: "May 10, 2024", sub: "ESG Report - Q1 2024" },
  { id: "score", label: "Compliance Score", value: "98%", sub: "Excellent" },
] as const;

export const REPORT_TYPES = [
  { id: "ghg",  name: "GHG Protocol Report",     sub: "Standard GHG inventory report aligned with the GHG Protocol.", cta: "Generate" },
  { id: "scope",name: "Scope 1/2/3 Report",       sub: "Comprehensive report across Scope 1, 2 & 3 emissions.", cta: "Generate" },
  { id: "esg",  name: "ESG Report",              sub: "Environmental, Social & Governance performance report.", cta: "Generate" },
  { id: "cdp",  name: "CDP Report",              sub: "Climate Disclosure Project report for climate change.", cta: "Generate" },
  { id: "tcfd", name: "TCFD Report",             sub: "Report aligned to the Task Force on Climate-related Financial Disclosures.", cta: "Generate" },
  { id: "csrd", name: "CSRD Report",             sub: "Corporate Sustainability Reporting Directive compliant report.", cta: "Generate" },
  { id: "custom",name: "Custom Report",          sub: "Build a custom report with the metrics and sections you need.", cta: "Create" },
  { id: "audit",name: "Audit Package",          sub: "Generate audit-ready package with supporting evidence.", cta: "Generate" },
] as const;

export const RECENT_REPORTS = [
  { id: 1, name: "ESG Report - Q1 2024",      sub: "Quarterly ESG performance report", framework: "ESG",      period: "Q1 2024", generated: "May 10, 2024 10:24 AM", status: "Completed", size: "2.4 MB" },
  { id: 2, name: "GHG Protocol Report - 2023", sub: "Annual GHG inventory report",    framework: "GHG Protocol", period: "2023", generated: "Apr 28, 2024 03:15 PM", status: "Completed", size: "3.1 MB" },
  { id: 3, name: "Scope 1-2-3 Emissions - 2023", sub: "Comprehensive scope report",  framework: "Scope 1/2/3", period: "2023", generated: "Apr 20, 2024 11:42 AM", status: "Completed", size: "2.7 MB" },
  { id: 4, name: "CDP Climate Change 2023",   sub: "CDP submission report",          framework: "CDP",     period: "2023", generated: "Apr 05, 2024 09:30 AM", status: "Completed", size: "1.8 MB" },
  { id: 5, name: "TCFD Report - 2023",        sub: "TCFD aligned disclosure",         framework: "TCFD",    period: "2023", generated: "Mar 28, 2024 02:11 PM", status: "Completed", size: "2.2 MB" },
  { id: 6, name: "CSRD Report - FY2023",      sub: "CSRD compliance report",          framework: "CSRD",    period: "FY2023", generated: "Mar 15, 2024 01:05 PM", status: "Completed", size: "3.6 MB" },
  { id: 7, name: "Custom Report - Supply Chain", sub: "Supplier emissions analysis", framework: "Custom", period: "Q4 2023", generated: "Feb 28, 2024 04:55 PM", status: "Completed", size: "1.2 MB" },
  { id: 8, name: "Audit Package - 2023",      sub: "Audit evidence & reports bundle", framework: "Audit Package", period: "2023", generated: "Feb 10, 2024 09:12 AM", status: "Completed", size: "12.4 MB" },
] as const;

export const REPORT_FRAMEWORK_BREAKDOWN = [
  { label: "GHG Protocol",  value: 9, percent: 32, color: "rgba(132,204,22,0.95)" },
  { label: "ESG",           value: 6, percent: 21, color: "rgba(16,185,129,0.95)" },
  { label: "Scope 1/2/3",   value: 5, percent: 18, color: "rgba(56,189,248,0.95)" },
  { label: "CDP",           value: 3, percent: 11, color: "rgba(244,63,94,0.95)" },
  { label: "TCFD",          value: 2, percent: 7,  color: "rgba(168,85,247,0.95)" },
  { label: "CSRD",          value: 2, percent: 7,  color: "rgba(245,158,11,0.95)" },
  { label: "Custom",        value: 1, percent: 4,  color: "rgba(148,163,184,0.6)" },
] as const;

export const REPORT_METRICS_POPULARITY = [
  { label: "Total Emissions (tCO₂e)", value: 28 },
  { label: "Scope 1 Emissions",      value: 28 },
  { label: "Scope 2 Emissions",      value: 28 },
  { label: "Scope 3 Emissions",      value: 24 },
  { label: "Energy Consumption",     value: 18 },
  { label: "Renewable Energy %",     value: 16 },
] as const;

/* ─────────────────  /dashboard/scenarios  ───────────────── */
export const SCENARIOS_KPIS = [
  { id: "baseline", label: "Baseline Emissions", value: "2,453", unit: "tCO₂e", sub: "Year 2023" },
  { id: "total", label: "Total Scenarios", value: "7", sub: "Across all time" },
  { id: "avg", label: "Avg Reductions", value: "18%", sub: "Compared to baseline" },
  { id: "highest", label: "Highest Reduction", value: "42%", sub: "Scenario: Net Zero Pathway" },
  { id: "active", label: "Active Scenarios", value: "3", sub: "Currently in progress" },
] as const;

export const SCENARIOS_LIST = [
  { id: 1, name: "Switch 50% Electricity to Renewable Energy", category: "Energy",     change: "50%", reduction: 1226, cost: "$120K", roi: "2.8x", status: "Projected",  updated: "May 10, 2024" },
  { id: 2, name: "Reduce Transportation Emissions by 20%",      category: "Logistics",  change: "20%", reduction: 312,  cost: "$45K",  roi: "3.2x", status: "Projected",  updated: "May 8, 2024" },
  { id: 3, name: "Optimize Supply Chain (Supplier Engagement)",   category: "Supply Chain", change: "15%", reduction: 285,  cost: "$35K",  roi: "2.1x", status: "Projected",  updated: "May 6, 2024" },
  { id: 4, name: "Improve Building Energy Efficiency by 30%",     category: "Operations", change: "30%", reduction: 410,  cost: "$70K",  roi: "2.6x", status: "In Progress", updated: "May 1, 2024" },
  { id: 5, name: "Reduce Business Travel Emissions by 30%",       category: "Travel",     change: "30%", reduction: 155,  cost: "$12K",  roi: "4.5x", status: "Completed",   updated: "Apr 25, 2024" },
  { id: 6, name: "Net Zero Pathway 2030",                          category: "Overall",    change: "—",  reduction: 1980, cost: "$1.2M", roi: "3.6x", status: "Projected",  updated: "Apr 20, 2024" },
  { id: 7, name: "Low Carbon Logistics Transition",                category: "Logistics",  change: "35%", reduction: 520,  cost: "$90K",  roi: "2.9x", status: "Draft",      updated: "Apr 18, 2024" },
] as const;

export const SCENARIO_TEMPLATES = [
  { id: 1, name: "Renewable Energy Transition",     sub: "Evaluate the impact of switching to renewable energy sources.", cta: "Use Template" },
  { id: 2, name: "Transportation Optimization",     sub: "Analyze impact of improving fuel efficiency and route optimization.", cta: "Use Template" },
  { id: 3, name: "Supply Chain Decarbonization",    sub: "Assess supplier engagement and low-carbon sourcing.", cta: "Use Template" },
  { id: 4, name: "Energy Efficiency Upgrade",        sub: "Simulate efficiency improvements of buildings and operations.", cta: "Use Template" },
  { id: 5, name: "Net Zero Pathway",                 sub: "Build and evaluate a complete net zero transition pathway.", cta: "Use Template" },
] as const;

export const SCENARIO_REDUCTION_BREAKDOWN = [
  { label: "Scope 1", value: 306, percent: 25, color: "rgba(132,204,22,0.95)" },
  { label: "Scope 2", value: 552, percent: 45, color: "rgba(56,189,248,0.95)" },
  { label: "Scope 3", value: 368, percent: 30, color: "rgba(168,85,247,0.95)" },
] as const;
