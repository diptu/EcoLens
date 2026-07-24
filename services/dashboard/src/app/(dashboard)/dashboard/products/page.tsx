/**
 * /dashboard/products — placeholder.
 * Will be built out next; for now shows a "coming soon" page so
 * the sidebar nav doesn't 404.
 */
import { Construction } from "lucide-react";

export const metadata = { title: "Products — EcoLens" };

export default function ProductsPage() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center rounded-xl border border-white/5 bg-white/[0.02] p-8 text-center">
      <Construction className="h-12 w-12 text-emerald-300" />
      <h1 className="mt-4 text-2xl font-bold text-white">products coming soon</h1>
      <p className="mt-2 max-w-md text-sm text-white/60">
        This page is part of the planned dashboard. The sidebar nav lands here, but the
        data and views are still being designed. Try one of the live pages:
        <span className="block mt-2 text-emerald-300">
          /dashboard/home · /dashboard/actions · /dashboard/analytics
        </span>
      </p>
    </div>
  );
}
