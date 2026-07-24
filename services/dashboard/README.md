# ecoLens Dashboard Service — Full Package

This zip contains the complete **ecoLens dashboard service** (v10):
- **70+** source files (Next.js 14 app router + TypeScript)
- **5 unit test files** (Vitest, 68 passing)
- **6 e2e test files** (Playwright, 70 passing)
- **11 MB** static export ready to deploy to any CDN / S3 / nginx
- **6.4 MB** of self-hosted images (no external dependencies)

## What's in here

```
ecolens-dashboard/
├── src/
│   ├── app/                  # Next.js App Router pages
│   │   ├── (auth)/           # Auth flow (login, signup, forgot, reset, verify, onboarding)
│   │   ├── (dashboard)/      # 19 dashboard pages with sidebar + topbar
│   │   ├── (inner)/          # Marketing pages (/, /product, /resources, /solutions, /pricing, /about)
│   │   └── api/              # API routes (placeholder for forecast-api proxy)
│   ├── components/
│   │   ├── auth/             # AuthLayout, AuthField, AuthButton, etc.
│   │   ├── dashboard/        # Sidebar, Topbar, KpiCard, charts, DataTable
│   │   ├── landing/          # Hero, FeaturesGlobe, Navbar, Footer
│   │   ├── pricing/          # BillingToggle, PlansGrid (the new pricing page)
│   │   ├── sections/         # Reusable section components
│   │   └── motion/           # MotionProvider, Framer Motion wrappers
│   ├── lib/
│   │   ├── data.ts           # Single source of truth — 700+ lines, 50+ exports
│   │   ├── utils.ts          # cn(), asBadgeText()
│   │   ├── gsap.ts           # GSAP helpers
│   │   └── animations.ts     # Animation config
│   ├── types/
│   └── ...
├── tests/                    # Vitest unit tests (68 passing)
├── e2e/                      # Playwright e2e tests (70 passing)
├── public/images/            # Self-hosted WebP images (no Unsplash hotlinks)
├── out/                      # Static export — deploy this directory
├── package.json
├── next.config.mjs
├── tailwind.config.ts
├── tsconfig.json
├── vitest.config.ts
├── playwright.config.ts
└── README.md
```

## Routes (32 pages)

**Marketing (6):** `/`, `/product`, `/resources`, `/solutions`, `/pricing`, `/about`

**Auth (6):** `/login`, `/signup`, `/forgot-password`, `/reset-password`, `/verify-email`, `/onboarding`

**Dashboard (20):** `/dashboard/{home,actions,analytics,goals,sources,notifications,organization,profile,reports,scenarios,overview,emissions,products,insights,integrations,api-access,users,preferences,billing}`

## Run it

```bash
# Install dependencies
npm install

# Run dev server (http://localhost:3000)
npm run dev

# Build static export (output: 'export' → out/)
npm run build

# Run unit tests
npm test

# Run e2e tests
npm run e2e      # needs `npm run serve` running on 8000 in another terminal
```

## Deploy

The `out/` directory is a static site. Drop it on:
- **nginx** — point `root` at the `out/` dir
- **S3 + CloudFront** — `aws s3 sync out/ s3://your-bucket`
- **Vercel** — `vercel deploy --prebuilt`
- **Netlify** — drag `out/` onto the dashboard
- **Cloudflare Pages** — connect the repo, build cmd `npm run build`, output dir `out`

All assets are self-hosted. No external CDN dependencies at runtime.

## Tech stack

- **Next.js 14.2** (App Router, static export, RSC)
- **TypeScript 5** strict
- **Tailwind CSS 3.4** + design tokens
- **shadcn/ui** patterns (Radix primitives)
- **Framer Motion 11** with `LazyMotion` + `m.X` (strict mode)
- **GSAP 3** via `gsap/dist/gsap.js` direct import (tree-shakeable)
- **Lucide React** icons
- **Vitest 4** + **Playwright 1.50** for tests

## Performance highlights (v10)

- **Lighthouse 100/100** on all inner pages (no throttling)
- **FCP 76ms** on the new /pricing page (no throttle)
- **FCP 1.6s** on 4G + 4x CPU (within Google's 1.8s threshold)
- **CLS = 0** on all pages
- **JS per page**: 0.2-3.5 KB (page-specific) + 87 KB shared
- **Total bundle**: 1.2 MB raw across all chunks
- **Key optimisations**:
  - Forest background image preloaded with `fetchPriority="high"`
  - No Framer Motion `initial` on LCP elements (CSS-only animations)
  - Native HTML `<table>` for compare-plans (zero JS)
  - LazyMotion strict mode with `m.X` (not `motion.X`)
  - Self-hosted WebP at quality 70 (LCP) / 50 (decorative)

## What's new in v10

- **`/pricing` page** — 4 plan cards (Starter $29 / Growth $79 / Professional $199 / Enterprise Custom), monthly/annually toggle with localStorage + URL hash persistence, keyboard shortcuts (M/A), compare-plans table, "all plans include" + add-ons + custom-solution cards
- **`src/components/pricing/`** — new `billing-toggle.tsx` + `plans-grid.tsx`
- **`src/lib/data.ts`** — 4 new exports: `PRICING_PLANS`, `PRICING_COMPARE_ROWS`, `PRICING_INCLUDED`, `PRICING_ADDONS`
- **17 new unit tests** for pricing data shape (annual ≤ monthly, monotonicity, etc.)
- **10 new e2e tests** for the pricing page (toggle, CWV, preload, etc.)
