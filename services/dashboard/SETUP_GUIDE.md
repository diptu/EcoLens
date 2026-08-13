# EcoLens Dashboard — Setup Guide

> Companion to `README.md` and `README-FIRST.md`. This guide covers
> running the project from the zip package.

## Quick start (5 steps)

```bash
# 1. Install dependencies (~30 seconds)
npm install

# 2. Run the unit tests
npm test                          # vitest, headless
npm run test:watch                # watch mode

# 3. Run the dev server
npm run dev                       # http://localhost:3000/

# 4. Build for production (static export)
npm run build                     # output → ./out/

# 5. Serve the built site locally
npm run serve                     # http://localhost:3000/
```

## What this zip contains

```
dashboard-pkg/
├── src/                    # All source code (TypeScript + React)
│   ├── app/                # Next.js App Router
│   │   ├── (auth)/         # login, signup, forgot-password, etc.
│   │   ├── (dashboard)/    # the main app
│   │   │   └── dashboard/
│   │   │       ├── admin/        # admin panel (models, jobs, anomaly, etc.)
│   │   │       ├── forecast/
│   │   │       ├── emissions/
│   │   │       └── ...           # 30+ pages
│   │   └── (inner)/        # landing pages (pricing, about, etc.)
│   ├── components/         # reusable UI primitives
│   ├── lib/                # data layer, mock auth, utils
│   └── types/              # type declarations
├── tests/unit/             # Vitest unit tests (212 tests)
├── e2e/                    # Playwright e2e tests (164 tests)
├── public/images/          # Self-hosted photos (15+)
├── out/                    # pre-built static export (deployable)
├── package.json
├── tsconfig.json
├── tailwind.config.ts
├── next.config.mjs
├── vitest.config.ts
├── playwright.config.ts
└── README-FIRST.md
```

## Mock users (auth is in-memory)

| Email | Username | Role | Password |
|---|---|---|---|
| `diptu@ecolens.com` | `diptu` | admin | `Hello123` |
| `diptu@ecolens.app` | `diptu.app` | admin | `Hello123` |
| `demo@ecolens.app` | `demo` | analyst | `demo1234` |

The auth is **client-side localStorage** for the demo. In production
this would be Auth0 / Cognito / your own backend.

## Available routes (highlights)

### Public
- `/` (landing)
- `/pricing/`
- `/product/`
- `/about/`
- `/login/`, `/signup/`, `/forgot-password/`

### Dashboard (auth required)
- `/dashboard/home/`
- `/dashboard/overview/`
- `/dashboard/forecast/`
- `/dashboard/emissions/`
- `/dashboard/forecasting/` (water monitoring)
- `/dashboard/live-monitoring/`
- `/dashboard/alerts/`
- `/dashboard/insights/`
- `/dashboard/scenarios/`
- `/dashboard/sources/`
- `/dashboard/reports/`
- ...30+ more

### Admin (admin role only)
- `/dashboard/admin/`
- `/dashboard/admin/models/`
- `/dashboard/admin/data/`
- `/dashboard/admin/jobs/`
- `/dashboard/admin/anomaly-detection/` ← newest
- `/dashboard/admin/users/`
- `/dashboard/admin/system/`

## Stack

- **Next.js 14** (App Router, static export, no SSR)
- **React 18**
- **TypeScript 5**
- **Tailwind CSS 3** with custom emerald/lime palette
- **shadcn/ui-style** primitives (Card, KpiCard, DataTable, etc.)
- **Framer Motion** (with `LazyMotion` + `m.X`)
- **GSAP** (direct import for treeshaking bypass)
- **Lucide React** (icons)
- **Vitest** (unit) + **Playwright** (e2e)
- **Mock auth** (localStorage, no backend)

## Why static export

This dashboard is statically exported (`output: "export"` in
`next.config.mjs`) and deployed to a CDN. There is no server, no DB
connection, no API. All data is generated client-side from the
mock data layer in `src/lib/`.

## Performance

- Light green palette: emerald-100/200/300 (one shade lighter than default)
- All images self-hosted in `public/images/`
- Below-fold sections lazy-loaded with `next/dynamic({ ssr: false })`
- LazyMotion + `m.X` (not `motion.X`) for Framer Motion
- CSS-only animations where possible (no GSAP for hero)
- `prefers-reduced-motion` respected at 3 levels

## Where to start reading the code

1. `src/lib/auth.ts` — mock auth + `MOCK_USERS`
2. `src/lib/admin.ts` — admin data layer (models, jobs, **anomalies**)
3. `src/lib/data.ts` — single source of truth for dashboard data
4. `src/components/dashboard/sidebar.tsx` — nav + role guard
5. `src/app/(dashboard)/dashboard/admin/anomaly-detection/page.tsx` — newest page

## Deploying

```bash
# Build
npm run build

# The `out/` directory is fully static — drop it on any CDN:
#   - Cloudflare Pages
#   - Netlify
#   - Vercel (output: 'export' compatible)
#   - S3 + CloudFront
#   - Nginx
#   - GitHub Pages
```

## License

Internal demo. No commercial use.
