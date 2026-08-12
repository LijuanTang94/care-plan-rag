import Link from "next/link";
import { listOrders } from "@/lib/data";
import type { Paginated, OrderBrief } from "@/lib/types";
import { Card, EmptyState, LinkButton, PageHeader, StatusBadge } from "@/components/ui";
import { BackendError } from "@/components/BackendError";
import { Filters } from "@/components/Filters";

export const dynamic = "force-dynamic";

const PAGE_SIZE = 10;

export default async function DashboardPage({
  searchParams,
}: PageProps<"/">) {
  const sp = await searchParams;
  const page = Math.max(1, Number(sp.page ?? 1) || 1);
  const status = typeof sp.status === "string" ? sp.status : undefined;
  const patient_name = typeof sp.q === "string" ? sp.q : undefined;

  let data: Paginated<OrderBrief> | null = null;
  let error: string | null = null;
  try {
    data = await listOrders({ page, page_size: PAGE_SIZE, status, patient_name });
  } catch (e) {
    error = e instanceof Error ? e.message : "Failed to load orders";
  }

  return (
    <div>
      <PageHeader
        title="Care plans"
        subtitle="Every generation request, its status, and the resulting plan."
        action={<LinkButton href="/orders/new">New care plan</LinkButton>}
      />

      <Filters status={status} q={patient_name} />

      {error ? (
        <BackendError message={error} />
      ) : !data || data.results.length === 0 ? (
        <EmptyState
          title="No care plans yet"
          hint="Create one from patient, provider, and medication details — it’s generated asynchronously and grounded in retrieved clinical guidelines."
          cta={<LinkButton href="/orders/new">New care plan</LinkButton>}
        />
      ) : (
        <>
          <Card className="overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
                  <th className="px-4 py-3 font-semibold">#</th>
                  <th className="px-4 py-3 font-semibold">Patient</th>
                  <th className="px-4 py-3 font-semibold">Medication</th>
                  <th className="px-4 py-3 font-semibold">Status</th>
                  <th className="px-4 py-3 font-semibold">Created</th>
                </tr>
              </thead>
              <tbody>
                {data.results.map((o) => (
                  <tr key={o.id} className="border-b border-line/60 last:border-0 hover:bg-background">
                    <td className="px-4 py-3 text-muted">
                      <Link href={`/orders/${o.id}`} className="font-medium text-accent hover:underline">
                        {o.id}
                      </Link>
                    </td>
                    <td className="px-4 py-3">
                      <Link href={`/orders/${o.id}`} className="hover:underline">
                        {o.patient_name}
                      </Link>
                    </td>
                    <td className="px-4 py-3">{o.medication_name}</td>
                    <td className="px-4 py-3">
                      <StatusBadge status={o.status} />
                    </td>
                    <td className="px-4 py-3 text-muted">{formatDate(o.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
          <Pagination page={page} count={data.count} pageSize={PAGE_SIZE} sp={sp} />
        </>
      )}
    </div>
  );
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

function Pagination({
  page,
  count,
  pageSize,
  sp,
}: {
  page: number;
  count: number;
  pageSize: number;
  sp: Record<string, string | string[] | undefined>;
}) {
  const totalPages = Math.max(1, Math.ceil(count / pageSize));
  const mk = (p: number) => {
    const params = new URLSearchParams();
    if (typeof sp.status === "string") params.set("status", sp.status);
    if (typeof sp.q === "string") params.set("q", sp.q);
    params.set("page", String(p));
    return `/?${params.toString()}`;
  };
  return (
    <div className="mt-4 flex items-center justify-between text-sm text-muted">
      <span>
        Page {page} of {totalPages} · {count} total
      </span>
      <div className="flex gap-2">
        {page > 1 ? (
          <Link href={mk(page - 1)} className="rounded-md border border-line bg-surface px-3 py-1.5 hover:bg-background">
            Previous
          </Link>
        ) : null}
        {page < totalPages ? (
          <Link href={mk(page + 1)} className="rounded-md border border-line bg-surface px-3 py-1.5 hover:bg-background">
            Next
          </Link>
        ) : null}
      </div>
    </div>
  );
}
