/**
 * (auth) route group layout — bypasses the (inner) navbar/footer
 * and the (dashboard) sidebar. Renders a bare <html>/<body>-neutral
 * shell so the auth pages can take over the full viewport.
 */
import { MotionProvider } from "@/components/motion/motion-provider";

export default function AuthRootLayout({ children }: { children: React.ReactNode }) {
  return <MotionProvider>{children}</MotionProvider>;
}
