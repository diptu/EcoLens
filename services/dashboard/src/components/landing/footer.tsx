/**
 * Footer — link columns + brand mark + copyright.
 */
"use client";

import Link from "next/link";

const COLUMNS: Array<{ title: string; links: Array<{ label: string; href: string }> }> = [
  {
    title: "Product",
    links: [
      { label: "Features",       href: "/features" },
      { label: "Pricing",        href: "/pricing" },
      { label: "Integrations",   href: "/integrations" },
      { label: "Changelog",      href: "/changelog" },
    ],
  },
  {
    title: "Solutions",
    links: [
      { label: "For Enterprises", href: "/enterprise" },
      { label: "For SMBs",        href: "/smb" },
      { label: "For Governments", href: "/government" },
      { label: "For ESG Teams",   href: "/esg" },
    ],
  },
  {
    title: "Resources",
    links: [
      { label: "Documentation", href: "/docs" },
      { label: "Blog",          href: "/blog" },
      { label: "Case Studies",  href: "/case-studies" },
      { label: "API Reference", href: "/api" },
    ],
  },
  {
    title: "Company",
    links: [
      { label: "About",   href: "/about" },
      { label: "Careers", href: "/careers" },
      { label: "Contact", href: "/contact" },
      { label: "Press",   href: "/press" },
    ],
  },
];

export function Footer() {
  return (
    <footer className="border-t border-white/5 bg-[#050a08]">
      <div className="mx-auto max-w-7xl px-6 py-16">
        <div className="grid gap-10 md:grid-cols-5">
          {/* Brand */}
          <div className="md:col-span-1">
            <div className="flex items-center gap-2">
              <div className="grid h-8 w-8 place-items-center rounded-full bg-gradient-to-br from-emerald-400 to-lime-300">
                <span className="text-sm font-bold text-black">E</span>
              </div>
              <span className="text-lg font-bold text-white">EcoLens</span>
            </div>
            <p className="mt-4 max-w-xs text-sm text-white/60">
              AI-powered carbon accounting for a regenerative economy.
            </p>
          </div>

          {/* Link columns */}
          {COLUMNS.map((column) => (
            <div key={column.title}>
              <h3 className="text-sm font-semibold text-white">{column.title}</h3>
              <ul className="mt-4 space-y-2">
                {column.links.map((link) => (
                  <li key={link.href}>
                    <Link
                      href={link.href}
                      className="text-sm text-white/60 transition-colors hover:text-white"
                    >
                      {link.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="mt-12 flex flex-col items-center justify-between gap-4 border-t border-white/5 pt-6 text-sm text-white/50 md:flex-row">
          <p>© {new Date().getFullYear()} EcoLens. All rights reserved.</p>
          <div className="flex items-center gap-6">
            <Link href="/privacy" className="hover:text-white">Privacy</Link>
            <Link href="/terms" className="hover:text-white">Terms</Link>
            <Link href="/security" className="hover:text-white">Security</Link>
          </div>
        </div>
      </div>
    </footer>
  );
}
