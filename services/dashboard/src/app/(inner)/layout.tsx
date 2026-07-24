/**
 * Inner layout — wraps /product, /resources, /solutions with the
 * site Navbar and Footer (which the home page renders inline because
 * it has its own hero composition).
 *
 * Wraps in <MotionProvider> so the navbar's `m.header` initial state
 * (`initial={{ y: -20, opacity: 0 }}` → `animate={{ y: 0, opacity: 1 }}`)
 * actually hydrates. Without the provider, the navbar is stuck at
 * `opacity: 0, transform: translateY(-20px)` because LazyMotion strict
 * mode can't find the domAnimation features.
 */
import type { ReactNode } from "react";

import { Footer } from "@/components/landing/footer";
import { Navbar } from "@/components/landing/navbar";
import { MotionProvider } from "@/components/motion/motion-provider";

export default function InnerLayout({ children }: { children: ReactNode }) {
  return (
    <MotionProvider>
      <div className="min-h-screen bg-[#050a08] text-white">
        <Navbar />
        {children}
        <Footer />
      </div>
    </MotionProvider>
  );
}
