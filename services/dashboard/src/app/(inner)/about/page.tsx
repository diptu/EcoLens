/**
 * /about — static placeholder page.
 * Self-contained company info stub. Uses no client JS beyond the
 * Navbar/Footer already provided by the (inner) layout.
 */
import { CtaBanner } from "@/components/sections/cta-banner";

export const metadata = {
  title: "About — EcoLens",
  description: "Our mission: make carbon intelligence accessible to every organization.",
};

const VALUES = [
  { title: "Science first", body: "Every calculation is grounded in peer-reviewed methodologies and open data." },
  { title: "Transparent by default", body: "Audit-ready reports, open assumptions, no black boxes." },
  { title: "Built for action", body: "Insight without action is just data — we help you act." },
  { title: "Globally inclusive", body: "Country-specific factors and frameworks built in from day one." },
];

export default function AboutPage() {
  return (
    <main>
      <section className="relative isolate overflow-hidden py-24 md:py-32">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 -z-10"
          style={{
            background:
              "radial-gradient(ellipse at 50% 0%, rgba(132,204,22,0.15) 0%, transparent 50%)",
          }}
        />
        <div className="mx-auto max-w-7xl px-6">
          <div className="text-center">
            <span className="inline-flex items-center gap-2 rounded-full border border-emerald-400/30 bg-emerald-400/10 px-3 py-1 text-xs font-medium tracking-wider text-emerald-300">
              ABOUT US
            </span>
            <h1 className="mt-4 text-4xl font-extrabold leading-[1.1] tracking-tight text-white md:text-6xl">
              We&apos;re building the carbon{" "}
              <span className="bg-gradient-to-r from-lime-300 to-emerald-300 bg-clip-text text-transparent">
                intelligence layer
              </span>
            </h1>
            <p className="mx-auto mt-5 max-w-xl text-base leading-relaxed text-white/70 md:text-lg">
              EcoLens helps organizations measure, monitor, and reduce their carbon
              footprint with AI-powered insights and effortless reporting.
            </p>
          </div>

          <div className="mt-16 grid grid-cols-1 gap-5 md:grid-cols-2 lg:grid-cols-4">
            {VALUES.map((v) => (
              <div
                key={v.title}
                className="rounded-2xl border border-white/10 bg-white/[0.02] p-6 transition-colors hover:border-emerald-400/30"
              >
                <h3 className="text-lg font-semibold text-white">{v.title}</h3>
                <p className="mt-2 text-sm leading-relaxed text-white/60">{v.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <CtaBanner
        variant="minimal"
        heading="Join the mission"
        highlight={<span className="block text-lime-300">Build a better future with us.</span>}
        body="We're hiring engineers, climate scientists, and designers who care about impact."
        primary={{ label: "See Open Roles" }}
      />
    </main>
  );
}
