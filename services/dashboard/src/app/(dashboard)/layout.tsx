/**
 * Dashboard layout — wraps every /dashboard/* page with the
 * persistent sidebar (left) + topbar (with search, notifications, profile).
 *
 * Both shell components are client-side so they can read the
 * current pathname to highlight the active nav item.
 */
import type { ReactNode } from "react";

import { Sidebar } from "@/components/dashboard/sidebar";
import { Topbar } from "@/components/dashboard/topbar";
import { MotionProvider } from "@/components/motion/motion-provider";

export default function DashboardLayout({ children }: { children: ReactNode }) {
  return (
    <MotionProvider>
      <div className="min-h-screen bg-[#050a08] text-white">
        <Sidebar />
        <div className="lg:pl-64">
          <Topbar />
          <main className="relative isolate mx-auto max-w-[1600px] px-4 py-6 md:px-6">
            {children}
          </main>
        </div>
      </div>
    </MotionProvider>
  );
}
