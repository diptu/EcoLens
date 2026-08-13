# ecoLens Dashboard Service — Full Package

This zip contains the complete **ecoLens dashboard service**:
- **70** source files (Next.js 14 app router + TypeScript)
- **9** test files (Vitest unit tests + Playwright e2e)
- **11 MB** static export ready to deploy to any CDN / S3 / nginx
- **6.4 MB** of self-hosted images (no external dependencies)

## What's in here

```
ecolens-dashboard/
├── src/
│   ├── app/                  # Next.js App Router pages
│   │   ├── (auth)/           # Auth flow (login, signup, forgot, reset, verify, onboarding)
│   │   ├── (dashboard)/      # 19 dashboard pages with sidebar + topbar
│   │   ├── (inner)/          # Marketing pages (/, /product, /resources, /solutions, etc.)
│   │   └── api/              # API routes (placeholder for forecast-api proxy)
│   ├── components/
│   │   ├── auth/             # AuthLayout, AuthField, AuthButton, etc.
│   │   ├── dashboard/        # Sidebar, Topbar, KpiCard, charts, DataTable
│   │   ├── landing/          # Hero, FeaturesGlobe, Navbar, Footer
│   │   ├── sections/         # Reusable section components
│   │   └── motion/           # MotionProvider, Framer Motion wrappers
│   ├── lib/
│   │   ├── data.ts           # Single source of truth — 600+ lines, 40+ exports
│   │   ├── utils.ts          # cn(), asBadgeText()
│   │   ├── gsap.ts           # GSAP helpers
│   │   └── animations.ts     # Animation config
│   ├── types/
│   └── ...
├── tests/                    # Vitest unit tests (51 passing)
├── e2e/                      # Playwright e2e tests (84 passing)
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

## Routes (25 pages)

**Marketing:** `/`, `/product`, `/resources`, `/solutions`, `/pricing`, `/about`
**Auth:** `/login`, `/signup`, `/forgot-password`, `/reset-password`, `/verify-email`, `/onboarding`
**Dashboard:** `/dashboard/{home,actions,analytics,goals,sources,notifications,organization,profile,reports,scenarios,overview,emissions,products,insights,integrations,api-access,users,preferences,billing}`

## Tech stack

- **Next.js 14.2** (App Router, static export, RSC)
- **TypeScript 5** strict
- **Tailwind CSS 3.4** + design tokens
- **shadcn/ui** patterns (Radix primitives)
- **Framer Motion 11** with `LazyMotion` + `m.X` (strict mode)
- **GSAP 3** via `gsap/dist/gsap.js` direct import (tree-shakeable)
- **Lucide React** icons
- **Vitest 4** + **Playwright 1.50** for tests
