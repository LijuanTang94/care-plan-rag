import Link from "next/link";
import { notFound } from "next/navigation";
import { ApiError } from "@/lib/api";
import { getOrder } from "@/lib/data";
import { Card, PageHeader } from "@/components/ui";
import { BackendError } from "@/components/BackendError";
import { LiveStatus } from "./LiveStatus";
import type { OrderDetail } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function OrderPage({ params }: PageProps<"/orders/[id]">) {
  const { id } = await params;
  const orderId = Number(id);
  if (!Number.isFinite(orderId)) notFound();

  let order: OrderDetail | null = null;
  let error: string | null = null;
  try {
    order = await getOrder(orderId);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    error = e instanceof Error ? e.message : "Failed to load order";
  }

  return (
    <div className="mx-auto max-w-3xl">
      <div className="mb-4">
        <Link href="/" className="text-sm text-accent hover:underline">
          ← Back to dashboard
        </Link>
      </div>

      {error ? (
        <BackendError message={error} />
      ) : order ? (
        <>
          <PageHeader
            title={`Order #${order.id}`}
            subtitle={`${order.patient_name} · ${order.medication_name}`}
          />
          <Card className="p-6">
            <LiveStatus id={order.id} initialStatus={order.status} initialPlan={order.care_plan} />
          </Card>
        </>
      ) : null}
    </div>
  );
}
