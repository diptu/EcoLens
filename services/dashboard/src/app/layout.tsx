import type { Metadata, Viewport } from "next";

import "./globals.css";

import { AuthProvider } from "@/lib/auth";
import { QueryProvider } from "@/components/providers/query-provider";

export const metadata: Metadata = {
  title: "EcoLens — Measure Today. Sustain Tomorrow.",
  description:
    "AI-powered carbon accounting. Measure, monitor, and reduce your carbon footprint with AI-driven insights.",
};

export const viewport: Viewport = {
  themeColor: "#050a08",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <head>
        {/* LCP element — preload the Earth (WebP is 33% smaller than JPG).
            fetchPriority="high" tells the browser this is the most
            important image to load. */}
        <link
          rel="preload"
          as="image"
          href="/images/earth.webp"
          fetchPriority="high"
        />
        {/* Tell the browser the same-origin (so no preconnect needed) */}
        <meta name="theme-color" content="#050a08" />
        {/* Performance: keep the document color dark to match the LCP
            so the LCP-to-paint transition is invisible. */}
        <style
          dangerouslySetInnerHTML={{
            __html: `html,body{background:#050a08;color:#fff}`,
          }}
        />
      </head>
      <body>
        <QueryProvider>
          <AuthProvider>{children}</AuthProvider>
        </QueryProvider>
      </body>
    </html>
  );
}
