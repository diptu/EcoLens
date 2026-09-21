/**
 * /dashboard/carbon/methodology — disabled.
 *
 * Route intentionally 404s. Its only linker, `/dashboard/carbon`, is
 * disabled too (see that route's own page.tsx) — this page became
 * unreachable from the UI once that happened, so it's removed as dead
 * code along with it rather than left orphaned. `lib/methodology.ts`
 * (this page's only caller — `CALCULATION_CHAIN`/`DATA_SOURCES`/
 * `FACTORS_WITH_CITATIONS`/`WORKED_EXAMPLES` and their types) has been
 * deleted entirely, along with its unit test
 * (`tests/unit/methodology.test.ts`). `lib/emissions.ts`'s
 * `fetchEmissionsTrace`/`EmissionsTrace`/`formatIntensity` were also
 * only used here (and by `/dashboard/carbon`, disabled in the same
 * pass) and have been removed too.
 */
import { notFound } from "next/navigation";

export default function CarbonMethodologyPage(): never {
  notFound();
}
