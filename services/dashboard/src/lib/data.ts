/**
 * Static/demo data layer. Every page in this app reads from here rather
 * than a live backend (see root TODO.md ECO-130: only home/analytics
 * were converted to real forecast-api calls; everything else still
 * reads this file). Edit here to change content globally; keep the
 * shapes in sync with tests/unit/{data,dashboard-data,pricing-data}.test.ts.
 */

export const DATA_VERSION = "1.0.0";

/* ───────────────────────── /solutions ───────────────────────── */

export const INDUSTRIES = [
  { title: "Manufacturing", image: "/images/industry-manufacturing.jpg", alt: "Manufacturing facility", href: "/solutions/manufacturing", body: "Track Scope 1-3 emissions across plants and supply chains.", metrics: { label: "Avg. reduction", value: "18%" } },
  { title: "Energy & Utilities", image: "/images/industry-energy.jpg", alt: "Energy infrastructure", href: "/solutions/energy", body: "Monitor generation mix and grid emissions intensity in real time.", metrics: { label: "Avg. reduction", value: "22%" } },
  { title: "Technology", image: "/images/industry-tech.jpg", alt: "Data center", href: "/solutions/technology", body: "Measure data-center and cloud-compute carbon footprint.", metrics: { label: "Avg. reduction", value: "15%" } },
  { title: "Transportation & Logistics", image: "/images/industry-transport.jpg", alt: "Logistics fleet", href: "/solutions/transportation", body: "Optimize fleet routing and fuel use for lower emissions.", metrics: { label: "Avg. reduction", value: "20%" } },
  { title: "Construction", image: "/images/industry-construction.jpg", alt: "Construction site", href: "/solutions/construction", body: "Track embodied carbon across materials and project phases.", metrics: { label: "Avg. reduction", value: "17%" } },
];

export const PLATFORM_FEATURES = [
  { title: "Real-time Monitoring", body: "Live emissions data from every connected source.", icon: "trend" },
  { title: "Automated Reporting", body: "Generate CDP, GHG Protocol, and TCFD-ready reports in minutes.", icon: "globe" },
  { title: "AI-Powered Insights", body: "Get reduction recommendations ranked by impact and cost.", icon: "brain" },
  { title: "Multi-source Integration", body: "Connect utilities, ERPs, and IoT sensors out of the box.", icon: "hub" },
  { title: "Scenario Planning", body: "Model reduction pathways before you commit capital.", icon: "flow" },
  { title: "Compliance Ready", body: "Stay aligned with evolving regional and global standards.", icon: "shield" },
];

export const SOLUTIONS_STATS = [
  { value: 500, suffix: "+", label: "Organizations onboarded", icon: "group" },
  { value: 30, suffix: "%", label: "Average emissions reduction", icon: "trend" },
  { value: 2, suffix: "M+", label: "Data points processed daily", icon: "hub" },
  { value: 98, suffix: "%", label: "Customer satisfaction", icon: "leaf" },
];

/* ───────────────────────── /product ───────────────────────── */

export const PRODUCT_FEATURES = [
  { title: "Unified Data Ingestion", body: "Connect every data source and let EcoLens normalize it automatically.", bullets: ["Connect utilities, ERPs, and IoT in minutes", "Automated unit conversion and normalization", "Continuous data-quality validation"], icon: "cloud", visual: "funnel" },
  { title: "Emissions Intelligence", body: "Understand exactly where your footprint comes from.", bullets: ["Scope 1, 2, and 3 breakdowns", "Region- and facility-level granularity", "Anomaly detection on every data point"], icon: "chart", visual: "chart" },
  { title: "Forecasting", body: "See where your emissions are headed, not just where they've been.", bullets: ["LSTM-based demand and emissions forecasts", "Conformal-calibrated confidence bands", "Scenario-adjusted projections"], icon: "globe", visual: "donut" },
  { title: "Reduction Planning", body: "Turn insight into an actionable, prioritized roadmap.", bullets: ["AI-ranked reduction opportunities", "Cost/effort/impact scoring", "Roadmap tracking against targets"], icon: "target", visual: "wind" },
  { title: "Reporting & Compliance", body: "Export audit-ready reports for every major framework.", bullets: ["One-click CDP/GHG Protocol exports", "Audit-ready data lineage", "Custom report builder"], icon: "doc", visual: "report" },
  { title: "Team Collaboration", body: "Keep every stakeholder aligned on the same goals.", bullets: ["Role-based access across teams", "Shared goals and accountability", "Org-wide notifications"], icon: "leaf", visual: "brain" },
];

export const PRODUCT_STEPS = [
  { number: 1, title: "Connect your sources", body: "Link utilities, ERPs, and sensors — no code required.", icon: "cloud" },
  { number: 2, title: "We calculate your footprint", body: "Automated Scope 1-3 calculations, validated continuously.", icon: "chart" },
  { number: 3, title: "Get AI-ranked recommendations", body: "See exactly which reductions move the needle.", icon: "brain" },
  { number: 4, title: "Track and report progress", body: "Monitor goals and export compliance-ready reports.", icon: "doc" },
];

export const PRODUCT_PILL_FEATURES = [
  { title: "Real-time data", body: "Live emissions figures, not last quarter's spreadsheet.", icon: "cloud" },
  { title: "AI-powered", body: "Recommendations ranked by real impact and cost.", icon: "brain" },
  { title: "Audit-ready", body: "Every number traces back to its source.", icon: "doc" },
];

/* ───────────────────────── /resources ───────────────────────── */

export const CATEGORIES = [
  { title: "Guides", body: "Step-by-step playbooks for every stage of your journey.", resourceCount: 24, href: "/resources/guides", icon: "book" },
  { title: "Reports", body: "Industry benchmarks and original research.", resourceCount: 12, href: "/resources/reports", icon: "chart" },
  { title: "Templates", body: "Ready-to-use trackers and calculators.", resourceCount: 18, href: "/resources/templates", icon: "doc" },
  { title: "Webinars", body: "Live and recorded sessions with sustainability experts.", resourceCount: 9, href: "/resources/webinars", icon: "video" },
  { title: "Case Studies", body: "How real organizations cut emissions with EcoLens.", resourceCount: 15, href: "/resources/case-studies", icon: "case" },
  { title: "Compliance", body: "Regulatory guides for every major framework.", resourceCount: 11, href: "/resources/compliance", icon: "shield" },
];

export const FEATURED_RESOURCES = [
  { type: "Guide", title: "The Complete Guide to Scope 3 Emissions", body: "Everything you need to measure your value-chain footprint.", meta: "12 min read", level: "Intermediate", image: "/images/resource-1.jpg", alt: "Guide cover", href: "/resources/scope-3-guide" },
  { type: "Report", title: "2026 State of Corporate Sustainability", body: "Benchmarks across 500+ organizations.", meta: "28 pages", level: "All levels", image: "/images/resource-2.jpg", alt: "Report cover", href: "/resources/state-of-sustainability" },
  { type: "Template", title: "GHG Protocol Reporting Template", body: "A ready-to-fill Scope 1/2/3 reporting workbook.", meta: "Spreadsheet", level: "Beginner", image: "/images/resource-3.jpg", alt: "Template preview", href: "/resources/ghg-template" },
  { type: "Case Study", title: "How Acme Manufacturing Cut Emissions 22%", body: "A 12-month reduction roadmap, step by step.", meta: "8 min read", level: "Intermediate", image: "/images/resource-4.jpg", alt: "Case study cover", href: "/resources/acme-case-study" },
  { type: "Webinar", title: "Forecasting Emissions with Machine Learning", body: "How conformal prediction improves planning confidence.", meta: "45 min", level: "Advanced", image: "/images/resource-1.jpg", alt: "Webinar thumbnail", href: "/resources/ml-forecasting-webinar" },
];

export const TOOLS = [
  { title: "Carbon Footprint Calculator", body: "Estimate your organization's baseline in minutes.", cta: "Try Calculator", icon: "calc" },
  { title: "Data Source Checklist", body: "Make sure you're capturing every emissions source.", cta: "Get Checklist", icon: "db" },
  { title: "Reduction ROI Estimator", body: "Compare cost and impact across initiatives.", cta: "Estimate ROI", icon: "trend" },
  { title: "Compliance Readiness Assessment", body: "See how ready you are for CDP/TCFD reporting.", cta: "Start Assessment", icon: "shield" },
];

export const RESOURCE_STATS = [
  { value: 89, suffix: "+", label: "Resources published", icon: "doc" },
  { value: 50, suffix: "K+", label: "Downloads", icon: "chart" },
  { value: 4.8, suffix: "/5", label: "Average rating", icon: "target" },
  { value: 12, suffix: "", label: "New this month", icon: "trend" },
];

export const POPULAR_TAGS = ["Scope 3", "GHG Protocol", "Net Zero", "CDP", "Forecasting", "Compliance"];

/* ───────────────────────── /pricing ───────────────────────── */

export const PRICING_PLANS = [
  {
    id: "starter",
    name: "Starter",
    description: "For small teams getting started with emissions tracking.",
    icon: "leaf",
    cta: { label: "Start Free Trial", href: "/signup" },
    price: { monthly: 99, annually: 79 },
    customLabel: undefined as string | undefined,
    features: ["Up to 3 data sources", "Monthly reporting", "Scope 1 & 2 tracking", "Email support", "1 user seat"],
    highlighted: false,
  },
  {
    id: "growth",
    name: "Growth",
    description: "For growing organizations that need deeper insight.",
    icon: "trend",
    cta: { label: "Start Free Trial", href: "/signup" },
    price: { monthly: 299, annually: 239 },
    customLabel: undefined as string | undefined,
    features: ["Up to 15 data sources", "Weekly reporting", "Scope 1, 2 & 3 tracking", "AI reduction recommendations", "Priority support", "10 user seats"],
    highlighted: true,
  },
  {
    id: "professional",
    name: "Professional",
    description: "For established teams managing multi-site operations.",
    icon: "hub",
    cta: { label: "Start Free Trial", href: "/signup" },
    price: { monthly: 799, annually: 639 },
    customLabel: undefined as string | undefined,
    features: ["Unlimited data sources", "Real-time reporting", "Demand + emissions forecasting", "Custom scenario planning", "Dedicated support", "Unlimited seats"],
    highlighted: false,
  },
  {
    id: "enterprise",
    name: "Enterprise",
    description: "For global organizations with custom compliance needs.",
    icon: "shield",
    cta: { label: "Contact Sales", href: "/contact" },
    price: { monthly: null, annually: null },
    customLabel: "Custom",
    features: ["Everything in Professional", "Custom integrations", "Dedicated success manager", "SLA-backed uptime", "SSO / SAML", "Custom contract terms"],
    highlighted: false,
  },
] as const;

export const PRICING_COMPARE_ROWS = [
  { row: "Data sources", starter: "3", growth: "15", professional: "Unlimited", enterprise: "Unlimited" },
  { row: "Scope 1 & 2 tracking", starter: true, growth: true, professional: true, enterprise: true },
  { row: "Scope 3 tracking", starter: false, growth: true, professional: true, enterprise: true },
  { row: "AI recommendations", starter: false, growth: true, professional: true, enterprise: true },
  { row: "Demand forecasting", starter: false, growth: false, professional: true, enterprise: true },
  { row: "Custom integrations", starter: false, growth: false, professional: false, enterprise: true },
  { row: "SSO / SAML", starter: false, growth: false, professional: false, enterprise: true },
];

export const PRICING_INCLUDED = [
  "Unlimited historical data retention",
  "Bank-grade data encryption",
  "99.9% uptime SLA",
  "Free onboarding & migration",
  "API access for every plan",
  "Cancel or change plans anytime",
];

export const PRICING_ADDONS = [
  { name: "Extra data source", price: "$15/mo" },
  { name: "Additional user seat", price: "$25/mo" },
  { name: "Advanced forecasting module", price: "$199/mo" },
  { name: "Dedicated onboarding", price: "$500 one-time" },
];

/* ───────────────────────── shared small helpers ───────────────────────── */

type Kpi = {
  id?: string;
  label: string;
  value: string;
  unit?: string;
  sub?: string;
  icon?: string;
  trend?: { direction: "up" | "down" | "flat"; text: string; goodWhen?: "up" | "down" };
};
type BreakdownItem = { label: string; value: number; percent: number; color: string };

const COLORS = ["rgba(132,204,22,0.9)", "rgba(56,189,248,0.9)", "rgba(168,85,247,0.8)", "rgba(244,63,94,0.8)", "rgba(251,191,36,0.85)", "rgba(148,163,184,0.6)"];

/* ───────────────────────── /dashboard/home ───────────────────────── */

export const HOME_KPIS: Kpi[] = [
  { id: "total-emissions", label: "Total Emissions", value: "2,453", unit: "tCO₂e", sub: "this month", trend: { direction: "down", text: "12% vs last month", goodWhen: "down" } },
  { id: "reduction", label: "Reduction vs Baseline", value: "18", unit: "%", sub: "YTD", trend: { direction: "up", text: "3pt vs last quarter", goodWhen: "up" } },
  { id: "active-goals", label: "Active Goals", value: "6", sub: "3 on track" },
  { id: "data-sources", label: "Data Sources Connected", value: "11", sub: "10 active" },
];

export const HOME_SCOPES = [
  { label: "Scope 1 (Direct)", value: 490, percent: 20, color: COLORS[0] },
  { label: "Scope 2 (Energy)", value: 736, percent: 30, color: COLORS[1] },
  { label: "Scope 3 (Value Chain)", value: 1227, percent: 50, color: COLORS[2] },
];

export const HOME_EMISSIONS_TREND = {
  labels: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
  current: [1850, 1920, 2050, 2180, 2300, 2400, 2350, 2420, 2380, 2450, 2453, 2400],
  baseline: [2200, 2250, 2300, 2350, 2400, 2450, 2480, 2500, 2520, 2540, 2550, 2560],
};

/* ───────────────────────── /dashboard/actions ───────────────────────── */

export const ACTIONS_KPIS: Kpi[] = [
  { label: "Total Recommendations", value: "24" },
  { label: "Potential Reduction", value: "1,240", unit: "tCO₂e/yr" },
  { label: "In Progress", value: "8" },
  { label: "Completed", value: "6" },
];

export const ACTION_RECOMMENDATIONS = [
  { id: 1, title: "Switch to renewable energy contracts", body: "Move facility power contracts to certified renewable providers.", category: "Energy", reduction: 320, cost: "$45K/year", roi: "3.2x", difficulty: "Medium" as const, priority: "High" as const, status: "In Progress" as const },
  { id: 2, title: "Upgrade to LED lighting facility-wide", body: "Replace remaining fluorescent fixtures across all sites.", category: "Facilities", reduction: 85, cost: "$12K/one-time", roi: "5.1x", difficulty: "Low" as const, priority: "Medium" as const, status: "Completed" as const },
  { id: 3, title: "Optimize fleet routing", body: "Use route-optimization software to cut fuel use and idle time.", category: "Transport", reduction: 145, cost: "$8K/year", roi: "4.4x", difficulty: "Medium" as const, priority: "High" as const, status: "Recommended" as const },
  { id: 4, title: "Install smart HVAC controls", body: "Add occupancy-based scheduling to reduce off-hours energy use.", category: "Facilities", reduction: 110, cost: "$22K/one-time", roi: "2.8x", difficulty: "Medium" as const, priority: "Medium" as const, status: "Recommended" as const },
  { id: 5, title: "Shift suppliers to low-carbon alternatives", body: "Prioritize vendors with published, verified emissions data.", category: "Supply Chain", reduction: 410, cost: "$0/year", roi: "6.0x", difficulty: "High" as const, priority: "High" as const, status: "In Progress" as const },
  { id: 6, title: "Enable remote-work default policy", body: "Reduce commute and office-energy emissions with a hybrid default.", category: "Operations", reduction: 60, cost: "$0/one-time", roi: "8.0x", difficulty: "Low" as const, priority: "Low" as const, status: "Recommended" as const },
];

export const ACTION_OVERVIEW = { total: 24, recommended: 10, inProgress: 8, notStarted: 0, completed: 6 };

export const ACTION_CATEGORIES_BREAKDOWN = [
  { label: "Energy", value: 320, reduction: 320, percent: 33, color: COLORS[0] },
  { label: "Supply Chain", value: 410, reduction: 410, percent: 42, color: COLORS[1] },
  { label: "Transport", value: 145, reduction: 145, percent: 15, color: COLORS[2] },
  { label: "Facilities", value: 100, reduction: 100, percent: 10, color: COLORS[3] },
];

export const ROADMAP = [
  { phase: "Short-Term (0-6mo)", items: ["Switch to renewable energy contracts", "Upgrade facility lighting to LED", "Enable remote-work default policy"] },
  { phase: "Mid-Term (6-18mo)", items: ["Optimize fleet routing", "Install smart HVAC controls"] },
  { phase: "Long-Term (18mo+)", items: ["Shift suppliers to low-carbon alternatives", "Facility-wide renewable retrofit"] },
];

/* ───────────────────────── /dashboard/analytics ───────────────────────── */

export const ANALYTICS_KPIS: Kpi[] = [
  { id: "total", label: "Total Emissions", value: "2,453", unit: "tCO₂e" },
  { id: "intensity", label: "Emissions Intensity", value: "0.42", unit: "tCO₂e/$K" },
  { id: "yoy", label: "YoY Change", value: "-12%" },
  { id: "forecast", label: "2026 Forecast", value: "28,650", unit: "tCO₂e" },
  { id: "goal", label: "Goal Progress", value: "42%" },
];

export const ANALYTICS_SCOPES = [
  { label: "Scope 1", value: 490, percent: 20, color: COLORS[0] },
  { label: "Scope 2", value: 736, percent: 30, color: COLORS[1] },
  { label: "Scope 3", value: 1227, percent: 50, color: COLORS[2] },
];

export const ANALYTICS_TREND = {
  labels: ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
  current: [1850, 1920, 2050, 2180, 2300, 2400, 2350, 2420, 2380, 2450, 2453, 2400],
  baseline: [2200, 2250, 2300, 2350, 2400, 2450, 2480, 2500, 2520, 2540, 2550, 2560],
};

export const ANALYTICS_INDUSTRY = [
  { label: "You", value: 0.42 },
  { label: "Industry Avg", value: 0.48 },
  { label: "Top Quartile", value: 0.23 },
  { label: "Peer Group A", value: 0.51 },
  { label: "Peer Group B", value: 0.39 },
];

export const ANALYTICS_OPPORTUNITIES = [
  { id: 1, name: "Renewable energy contracts", reduction: 320, percent: 15, cost: "Medium", effort: "Low", roi: "3.2x", priority: "High" as const },
  { id: 2, name: "Supplier engagement program", reduction: 410, percent: 20, cost: "Low", effort: "High", roi: "4.1x", priority: "High" as const },
  { id: 3, name: "Fleet route optimization", reduction: 145, percent: 8, cost: "Low", effort: "Medium", roi: "2.5x", priority: "Medium" as const },
  { id: 4, name: "Facility retrofit", reduction: 195, percent: 10, cost: "High", effort: "High", roi: "1.6x", priority: "Medium" as const },
  { id: 5, name: "Remote-work policy", reduction: 60, percent: 4, cost: "Low", effort: "Low", roi: "5.0x", priority: "Low" as const },
];
// percents intentionally total 57% -- "of total addressable emissions"
// (see dashboard-data.test.ts), not 100%; the remainder needs longer-
// horizon initiatives not yet modeled as discrete opportunities.
// Note: reduction opportunity percents intentionally total 57% here — the
// analytics page/test treat this as "of total addressable emissions",
// not 100% (a majority still requires longer-horizon initiatives).

/* ───────────────────────── /dashboard/goals ───────────────────────── */

export const GOALS_KPIS: Kpi[] = [
  { label: "Active Goals", value: "6" },
  { label: "On Track", value: "3" },
  { label: "At Risk", value: "2" },
  { label: "Completed", value: "1" },
];

export const GOAL_ROADMAP_DATA = {
  labels: ["2023", "2024", "2025", "2026", "2027", "2028", "2029", "2030"],
  actual: [3200, 2980, 2453, 2453, 2453, 2453, 2453, 2453],
  target: [3200, 2900, 2600, 2300, 2000, 1700, 1400, 1100],
  baseline: [3200, 3150, 3100, 3050, 3000, 2950, 2900, 2850],
};

export const YOUR_GOALS = [
  { id: 1, title: "Reduce Scope 1 & 2 by 30% by 2028", name: "Reduce Scope 1 & 2 by 30% by 2028", sub: "Emissions reduction target", status: "On Track" as const, progress: 62, category: "Emissions", type: "SBTi", target: "30% reduction", deadline: "Dec 2028" },
  { id: 2, title: "Achieve Net Zero by 2035", name: "Achieve Net Zero by 2035", sub: "Long-term climate commitment", status: "On Track" as const, progress: 24, category: "Emissions", type: "Corporate", target: "Net Zero", deadline: "Dec 2035" },
  { id: 3, title: "100% renewable energy by 2027", name: "100% renewable energy by 2027", sub: "Energy transition target", status: "At Risk" as const, progress: 45, category: "Energy", type: "Corporate", target: "100% renewable", deadline: "Dec 2027" },
  { id: 4, title: "Zero waste to landfill by 2026", name: "Zero waste to landfill by 2026", sub: "Waste & circularity target", status: "Behind" as const, progress: 30, category: "Waste", type: "Corporate", target: "Zero waste", deadline: "Dec 2026" },
  { id: 5, title: "Carbon-neutral shipping by 2029", name: "Carbon-neutral shipping by 2029", sub: "Transport emissions target", status: "On Track" as const, progress: 15, category: "Transport", type: "Corporate", target: "Carbon-neutral", deadline: "Dec 2029" },
  { id: 6, title: "CDP A-list by 2025", name: "CDP A-list by 2025", sub: "Disclosure & compliance target", status: "Completed" as const, progress: 100, category: "Compliance", type: "SBTi", target: "CDP A", deadline: "Dec 2025" },
];

export const GOAL_TYPES = [
  { label: "Emissions Reduction", value: 45, percent: 45, color: COLORS[0] },
  { label: "Energy Transition", value: 30, percent: 30, color: COLORS[1] },
  { label: "Waste & Circularity", value: 15, percent: 15, color: COLORS[2] },
  { label: "Compliance", value: 10, percent: 10, color: COLORS[3] },
];

export const UPCOMING_DEADLINES = [
  { id: 1, title: "CDP Climate Disclosure", name: "CDP Climate Disclosure", date: "Aug 12, 2026", daysLeft: 21 },
  { id: 2, title: "Q2 Scope 3 data submission", name: "Q2 Scope 3 data submission", date: "Jul 31, 2026", daysLeft: 9 },
  { id: 3, title: "Annual sustainability report", name: "Annual sustainability report", date: "Sep 5, 2026", daysLeft: 45 },
];

export const MILESTONES = [
  { id: 1, title: "Baseline year established", name: "Baseline year established", date: "Jan 2023", status: "Completed" as const },
  { id: 2, title: "First 10% reduction achieved", name: "First 10% reduction achieved", date: "Jun 2024", status: "Completed" as const },
  { id: 3, title: "Renewable energy contracts signed", name: "Renewable energy contracts signed", date: "Feb 2025", status: "Completed" as const },
  { id: 4, title: "30% reduction milestone", name: "30% reduction milestone", date: "Dec 2028", status: "On Track" as const },
  { id: 5, title: "Net zero target year", name: "Net zero target year", date: "Dec 2035", status: "Upcoming" as const },
];

/* ───────────────────────── /dashboard/sources ───────────────────────── */

export const SOURCES_KPIS: Kpi[] = [
  { label: "Total Sources", value: "11" },
  { label: "Active", value: "9" },
  { label: "Syncing", value: "1" },
  { label: "Data Points / day", value: "48,200" },
];

export const DATA_SOURCES = [
  { id: 1, name: "Grid Electricity (NSW1)", sub: "AEMO NEM dispatch feed", type: "Utility", status: "Active" as const, dataPoints: 8640, emissions: 812.4, lastSync: "5 min ago" },
  { id: 2, name: "Grid Electricity (VIC1)", sub: "AEMO NEM dispatch feed", type: "Utility", status: "Active" as const, dataPoints: 8640, emissions: 640.2, lastSync: "5 min ago" },
  { id: 3, name: "Natural Gas Meters", sub: "Facility metering", type: "Utility", status: "Active" as const, dataPoints: 2880, emissions: 310.8, lastSync: "12 min ago" },
  { id: 4, name: "Fleet Telematics", sub: "Vehicle GPS + fuel logs", type: "IoT", status: "Active" as const, dataPoints: 14400, emissions: 145.0, lastSync: "2 min ago" },
  { id: 5, name: "SAP ERP", sub: "Procurement & logistics data", type: "ERP", status: "Active" as const, dataPoints: 3200, emissions: 88.5, lastSync: "1 hour ago" },
  { id: 6, name: "Weather Feed (BoM)", sub: "Bureau of Meteorology observations", type: "External API", status: "Active" as const, dataPoints: 4320, emissions: 0, lastSync: "3 min ago" },
  { id: 7, name: "AEMO Market Data", sub: "Wholesale price & generation mix", type: "External API", status: "Active" as const, dataPoints: 5760, emissions: 0, lastSync: "1 min ago" },
  { id: 8, name: "Waste Management System", sub: "Vendor waste manifests", type: "Vendor", status: "Syncing" as const, dataPoints: 640, emissions: 42.1, lastSync: "syncing" },
  { id: 9, name: "Travel Booking Platform", sub: "Employee travel bookings", type: "Vendor", status: "Active" as const, dataPoints: 210, emissions: 60.3, lastSync: "6 hours ago" },
  { id: 10, name: "Legacy Facilities Sensor Net", sub: "Deprecated on-prem sensors", type: "IoT", status: "Inactive" as const, dataPoints: 0, emissions: 0, lastSync: "14 days ago" },
  { id: 11, name: "Supplier Emissions Portal", sub: "Upstream Scope 3 supplier data", type: "Vendor", status: "Active" as const, dataPoints: 128, emissions: 353.7, lastSync: "1 day ago" },
];

export const SOURCE_HEALTH = { healthy: 9, syncing: 1, inactive: 1, percent: 82 };

export const SOURCES_BY_TYPE: BreakdownItem[] = [
  { label: "Utility", value: 3, percent: 27, color: COLORS[0] },
  { label: "IoT", value: 2, percent: 18, color: COLORS[1] },
  { label: "ERP", value: 1, percent: 9, color: COLORS[2] },
  { label: "External API", value: 2, percent: 18, color: COLORS[3] },
  { label: "Vendor", value: 3, percent: 27, color: COLORS[4] },
];

export const SOURCE_BREAKDOWN: BreakdownItem[] = SOURCES_BY_TYPE;

export const SOURCE_ALERTS = [
  { id: 1, source: "Legacy Facilities Sensor Net", name: "Legacy Facilities Sensor Net", message: "No data received in 14 days", type: "sync failed", time: "14 days ago", severity: "High" as const },
  { id: 2, source: "Waste Management System", name: "Waste Management System", message: "Sync in progress, delayed 20 min", type: "sync delayed", time: "20 min ago", severity: "Low" as const },
];

export const POPULAR_INTEGRATIONS = [
  { id: 1, name: "SAP", category: "ERP", sub: "ERP & procurement data", color: "rgba(56,102,204,0.85)" },
  { id: 2, name: "Salesforce", category: "CRM", sub: "Customer & sales data", color: "rgba(56,189,248,0.85)" },
  { id: 3, name: "AWS", category: "Cloud", sub: "Cloud compute & storage usage", color: "rgba(251,146,60,0.85)" },
  { id: 4, name: "Workday", category: "HR", sub: "Employee & travel data", color: "rgba(132,204,22,0.85)" },
];

/* ───────────────────────── /dashboard/notifications ───────────────────────── */

export const NOTIFICATIONS_KPIS: Kpi[] = [
  { label: "Unread", value: "4" },
  { label: "High Priority", value: "2" },
  { label: "This Week", value: "10" },
  { label: "Actioned", value: "6" },
];

export const NOTIFICATION_LIST = [
  { id: 1, title: "Data source disconnected", body: "Legacy Facilities Sensor Net has not reported in 14 days.", message: "Legacy Facilities Sensor Net has not reported in 14 days.", type: "Data", color: "rose", priority: "High" as const, read: false, time: "2 hours ago" },
  { id: 2, title: "Goal at risk", body: "100% renewable energy by 2027 is trending behind schedule.", message: "100% renewable energy by 2027 is trending behind schedule.", type: "Goal", color: "emerald", priority: "High" as const, read: false, time: "5 hours ago" },
  { id: 3, title: "Monthly report ready", body: "Your May 2026 emissions report has been generated.", message: "Your May 2026 emissions report has been generated.", type: "Report", color: "purple", priority: "Medium" as const, read: false, time: "1 day ago" },
  { id: 4, title: "New recommendation available", body: "AI identified a new reduction opportunity worth 145 tCO₂e/yr.", message: "AI identified a new reduction opportunity worth 145 tCO₂e/yr.", type: "Recommendation", color: "sky", priority: "Medium" as const, read: true, time: "1 day ago" },
  { id: 5, title: "Milestone achieved", body: "30% reduction milestone is now on track.", message: "30% reduction milestone is now on track.", type: "Goal", color: "emerald", priority: "Low" as const, read: true, time: "2 days ago" },
  { id: 6, title: "Data sync completed", body: "Waste Management System finished syncing.", message: "Waste Management System finished syncing.", type: "Data", color: "blue", priority: "Low" as const, read: true, time: "3 days ago" },
  { id: 7, title: "Team member added", body: "Jordan Lee was added to your organization.", message: "Jordan Lee was added to your organization.", type: "Compliance", color: "amber", priority: "Low" as const, read: true, time: "4 days ago" },
  { id: 8, title: "CDP deadline approaching", body: "Climate disclosure is due in 21 days.", message: "Climate disclosure is due in 21 days.", type: "Compliance", color: "amber", priority: "High" as const, read: false, time: "5 days ago" },
  { id: 9, title: "Scenario comparison ready", body: "Your 'Aggressive Reduction' scenario finished modeling.", message: "Your 'Aggressive Reduction' scenario finished modeling.", type: "Anomaly", color: "purple", priority: "Medium" as const, read: true, time: "6 days ago" },
  { id: 10, title: "Welcome to EcoLens", body: "Your account setup is complete.", message: "Your account setup is complete.", type: "Report", color: "blue", priority: "Low" as const, read: true, time: "2 weeks ago" },
];

export const NOTIFICATION_TYPES_BREAKDOWN: BreakdownItem[] = [
  { label: "Alerts", value: 3, percent: 30, color: COLORS[3] },
  { label: "Reports", value: 2, percent: 20, color: COLORS[1] },
  { label: "Recommendations", value: 3, percent: 30, color: COLORS[0] },
  { label: "System", value: 2, percent: 20, color: COLORS[5] },
];

export const NOTIFICATION_CHANNELS = [
  { name: "Email", label: "Email", enabled: true },
  { name: "In-app", label: "In-app", enabled: true },
  { name: "Slack", label: "Slack", enabled: false },
  { name: "SMS", label: "SMS", enabled: false },
];

/* ───────────────────────── /dashboard/reports ───────────────────────── */

export const REPORTS_KPIS: Kpi[] = [
  { label: "Reports Generated", value: "34" },
  { label: "This Quarter", value: "8" },
  { label: "Scheduled", value: "3" },
  { label: "Frameworks Covered", value: "5" },
];

export const REPORT_TYPES = [
  { id: "ghg", name: "GHG Protocol", sub: "The most widely used corporate GHG accounting standard.", cta: "Generate" },
  { id: "cdp", name: "CDP Climate Change", sub: "Annual climate disclosure for investors and customers.", cta: "Generate" },
  { id: "tcfd", name: "TCFD", sub: "Climate-related financial risk disclosure.", cta: "Generate" },
  { id: "sasb", name: "SASB", sub: "Industry-specific sustainability accounting metrics.", cta: "Generate" },
  { id: "sec", name: "SEC Climate Disclosure", sub: "US SEC climate-related disclosure rules.", cta: "Generate" },
  { id: "iso", name: "ISO 14064", sub: "International GHG quantification and verification standard.", cta: "Generate" },
  { id: "custom", name: "Custom Report", sub: "Build a report with exactly the metrics you need.", cta: "Build" },
  { id: "board", name: "Board Summary", sub: "A concise summary for board and executive review.", cta: "Generate" },
];

export const RECENT_REPORTS = [
  { id: 1, name: "May 2026 Emissions Report", sub: "GHG Protocol · May 2026", type: "GHG Protocol", framework: "GHG Protocol", period: "May 2026", date: "2026-06-01", generated: "2026-06-01 09:15 AM", status: "Completed" as const, size: "2.4 MB" },
  { id: 2, name: "Q1 2026 CDP Submission", sub: "CDP · Q1 2026", type: "CDP", framework: "CDP", period: "Q1 2026", date: "2026-04-15", generated: "2026-04-15 02:40 PM", status: "Completed" as const, size: "5.1 MB" },
  { id: 3, name: "2025 Annual Sustainability Report", sub: "ESG · FY2025", type: "Custom", framework: "ESG", period: "FY2025", date: "2026-01-20", generated: "2026-01-20 11:05 AM", status: "Completed" as const, size: "8.7 MB" },
  { id: 4, name: "TCFD Climate Risk Disclosure", sub: "TCFD · FY2025", type: "TCFD", framework: "TCFD", period: "FY2025", date: "2025-12-10", generated: "2025-12-10 04:30 PM", status: "Completed" as const, size: "3.3 MB" },
  { id: 5, name: "April 2026 Emissions Report", sub: "GHG Protocol · Apr 2026", type: "GHG Protocol", framework: "GHG Protocol", period: "Apr 2026", date: "2026-05-01", generated: "2026-05-01 09:10 AM", status: "Completed" as const, size: "2.2 MB" },
  { id: 6, name: "Board Sustainability Summary Q1", sub: "Board Summary · Q1 2026", type: "Board Summary", framework: "Board Summary", period: "Q1 2026", date: "2026-04-05", generated: "2026-04-05 08:00 AM", status: "Completed" as const, size: "1.1 MB" },
  { id: 7, name: "SASB Metrics 2025", sub: "SASB · FY2025", type: "SASB", framework: "SASB", period: "FY2025", date: "2026-02-28", generated: "2026-02-28 03:20 PM", status: "Completed" as const, size: "4.0 MB" },
  { id: 8, name: "March 2026 Emissions Report", sub: "GHG Protocol · Mar 2026", type: "GHG Protocol", framework: "GHG Protocol", period: "Mar 2026", date: "2026-04-01", generated: "2026-04-01 09:05 AM", status: "Completed" as const, size: "2.3 MB" },
];

export const REPORT_FRAMEWORK_BREAKDOWN: BreakdownItem[] = [
  { label: "GHG Protocol", value: 14, percent: 41, color: COLORS[0] },
  { label: "CDP", value: 6, percent: 18, color: COLORS[1] },
  { label: "TCFD", value: 5, percent: 15, color: COLORS[2] },
  { label: "SASB", value: 4, percent: 12, color: COLORS[3] },
  { label: "Other", value: 5, percent: 14, color: COLORS[5] },
];

export const REPORT_METRICS_POPULARITY = [
  { label: "Scope 1 & 2 totals", value: 34 },
  { label: "Scope 3 breakdown", value: 22 },
  { label: "Emissions intensity", value: 18 },
  { label: "YoY trend", value: 15 },
];

/* ───────────────────────── /dashboard/scenarios ───────────────────────── */

export const SCENARIOS_KPIS: Kpi[] = [
  { label: "Active Scenarios", value: "7" },
  { label: "In Progress", value: "2" },
  { label: "Completed", value: "3" },
  { label: "Best ROI", value: "4.1x" },
];

export const SCENARIOS_LIST = [
  { id: 1, name: "Aggressive Reduction 2030", category: "Overall", status: "Projected" as const, reduction: 1200, change: "-49%", cost: "$1.1M", roi: "3.8x", updated: "2 days ago" },
  { id: 2, name: "Renewable Transition Fast-Track", category: "Energy", status: "In Progress" as const, reduction: 890, change: "-36%", cost: "$650K", roi: "4.1x", updated: "5 hours ago" },
  { id: 3, name: "Supply Chain Engagement", category: "Supply Chain", status: "Completed" as const, reduction: 410, change: "-17%", cost: "$0", roi: "3.2x", updated: "1 week ago" },
  { id: 4, name: "Fleet Electrification", category: "Logistics", status: "Draft" as const, reduction: 320, change: "-13%", cost: "$980K", roi: "2.1x", updated: "3 days ago" },
  { id: 5, name: "Facility Retrofit Program", category: "Operations", status: "Projected" as const, reduction: 195, change: "-8%", cost: "$420K", roi: "1.6x", updated: "1 day ago" },
  { id: 6, name: "Remote-Work Expansion", category: "Travel", status: "Completed" as const, reduction: 60, change: "-2%", cost: "$0", roi: "5.0x", updated: "2 weeks ago" },
  { id: 7, name: "Net Zero by 2032 (stretch)", category: "Overall", status: "Draft" as const, reduction: 2453, change: "-100%", cost: "$3.4M", roi: "1.9x", updated: "6 hours ago" },
];

export const SCENARIO_TEMPLATES = [
  { id: 1, name: "Renewable Energy Transition", sub: "Model a phased switch to 100% renewable contracts.", cta: "Use Template" },
  { id: 2, name: "Fleet Electrification", sub: "Compare EV transition timelines and cost curves.", cta: "Use Template" },
  { id: 3, name: "Supply Chain Engagement", sub: "Estimate impact of supplier-side reduction programs.", cta: "Use Template" },
  { id: 4, name: "Facility Retrofit", sub: "Model energy-efficiency retrofit ROI across sites.", cta: "Use Template" },
  { id: 5, name: "Net Zero Pathway", sub: "Build a full pathway to net zero by a target year.", cta: "Use Template" },
];

export const SCENARIO_REDUCTION_BREAKDOWN: BreakdownItem[] = [
  { label: "Energy", value: 890, percent: 38, color: COLORS[0] },
  { label: "Supply Chain", value: 410, percent: 18, color: COLORS[1] },
  { label: "Transport", value: 320, percent: 14, color: COLORS[2] },
  { label: "Facilities", value: 195, percent: 8, color: COLORS[3] },
  { label: "Other", value: 526, percent: 22, color: COLORS[5] },
];

/* ───────────────────────── /dashboard/organization ───────────────────────── */

export const ORG_OVERVIEW = {
  name: "Acme Sustainability Group",
  employees: 1240,
  locations: 5,
  industry: "Manufacturing",
  founded: 2008,
  hq: "Sydney, Australia",
  orgId: "ECO-ORG-10492",
  growth: 8,
  facilities: 4,
  fiscalYear: "Jul-Jun",
  framework: "GHG Protocol",
};

export const ORG_LOCATIONS = [
  { id: 1, name: "Sydney HQ", flag: "🇦🇺", type: "Headquarters" as const, employees: 420 },
  { id: 2, name: "Melbourne Office", flag: "🇦🇺", type: "Regional Office" as const, employees: 310 },
  { id: 3, name: "Brisbane Office", flag: "🇦🇺", type: "Office" as const, employees: 180 },
  { id: 4, name: "Perth Office", flag: "🇦🇺", type: "Office" as const, employees: 150 },
  { id: 5, name: "Adelaide Office", flag: "🇦🇺", type: "Office" as const, employees: 180 },
];

export const ORG_FACILITIES = [
  { id: 1, name: "Sydney Manufacturing Plant", location: "Sydney, NSW", area: "85,000 ft²", type: "Manufacturing" },
  { id: 2, name: "Melbourne Distribution Center", location: "Melbourne, VIC", area: "120,000 ft²", type: "Warehouse" },
  { id: 3, name: "Brisbane Assembly Facility", location: "Brisbane, QLD", area: "62,000 ft²", type: "Manufacturing" },
  { id: 4, name: "Sydney HQ Office Tower", location: "Sydney, NSW", area: "45,000 ft²", type: "Office" },
];

export const ORG_EMPLOYEES = {
  total: 1240,
  breakdown: [
    { label: "Manufacturing", value: 620, percent: 50, color: COLORS[0] },
    { label: "Operations", value: 310, percent: 25, color: COLORS[1] },
    { label: "Corporate", value: 186, percent: 15, color: COLORS[2] },
    { label: "Sales & Support", value: 124, percent: 10, color: COLORS[3] },
  ],
};

export const ORG_FRAMEWORKS = [
  { id: 1, name: "GHG Protocol", sub: "Primary reporting standard", role: "Primary", primary: true },
  { id: 2, name: "CDP", sub: "Investor climate disclosure", role: "Supporting", primary: false },
  { id: 3, name: "TCFD", sub: "Climate risk disclosure", role: "Supporting", primary: false },
  { id: 4, name: "SASB", sub: "Industry sustainability metrics", role: "Supporting", primary: false },
  { id: 5, name: "ISO 14064", sub: "GHG verification standard", role: "Supporting", primary: false },
];

/* ───────────────────────── /dashboard/profile ───────────────────────── */

export const PROFILE_USER = {
  name: "Jordan Lee",
  email: "jordan.lee@acme-sustainability.com",
  role: "Sustainability Manager",
  avatar: "/images/earth.jpg",
  bio: "Leading Acme's path to net zero, one data source at a time.",
  department: "Sustainability & ESG",
  location: "Sydney, Australia",
  memberSince: "Mar 2023",
  lastLogin: "Today, 9:12 AM",
  jobTitle: "Sustainability Manager",
  phone: "+61 4 1234 5678",
  language: "English (Australia)",
};

export const PROFILE_PREFERENCES = [
  { id: "dash", label: "Email digest frequency", hint: "How often you receive summary emails", value: "Weekly" },
  { id: "reportformat", label: "Default report format", hint: "Used when generating new reports", value: "PDF" },
  { id: "tz", label: "Time zone", hint: "Used for all dates and schedules", value: "Australia/Sydney" },
  { id: "units", label: "Units", hint: "Emissions and energy unit system", value: "Metric (tCO₂e)" },
  { id: "date", label: "Language", hint: "Display language across the app", value: "English" },
  { id: "theme", label: "Theme", hint: "Light or dark interface", value: "Dark" },
];

export const PROFILE_NOTIFICATION_CATEGORIES = [
  { id: "goals", label: "Goal alerts", body: "Notify me when a goal falls behind schedule.", enabled: true },
  { id: "alerts", label: "Data source issues", body: "Notify me when a data source disconnects or errors.", enabled: true },
  { id: "recs", label: "New recommendations", body: "Notify me when AI finds a new reduction opportunity.", enabled: true },
  { id: "reports", label: "Report generation", body: "Notify me when a scheduled report finishes generating.", enabled: true },
  { id: "activity", label: "Team activity", body: "Notify me about teammate actions on shared goals.", enabled: false },
  { id: "compliance", label: "Product updates", body: "Notify me about new EcoLens features and changes.", enabled: false },
];
