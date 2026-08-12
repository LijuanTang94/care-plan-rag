import Link from "next/link";
import { notFound } from "next/navigation";
import { ApiError } from "@/lib/api";
import { getPatient } from "@/lib/data";
import { Card, EmptyState, LinkButton, PageHeader, StatusBadge } from "@/components/ui";
import { BackendError } from "@/components/BackendError";
import type { PatientDetail } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function PatientPage({ params }: PageProps<"/patients/[id]">) {
  const { id } = await params;
  const pid = Number(id);
  if (!Number.isFinite(pid)) notFound();

  let patient: PatientDetail | null = null;
  let error: string | null = null;
  try {
    patient = await getPatient(pid);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    error = e instanceof Error ? e.message : "Failed to load patient";
  }

  return (
    <div>
      <div className="mb-4">
        <Link href="/patients" className="text-sm text-accent hover:underline">
          ← Back to patients
        </Link>
      </div>

      {error ? (
        <BackendError message={error} />
      ) : patient ? (
        <>
          <PageHeader
            title={`${patient.first_name} ${patient.last_name}`}
            subtitle={`MRN ${patient.mrn}${patient.dob ? ` · DOB ${patient.dob}` : ""}`}
            action={<LinkButton href="/orders/new">New care plan</LinkButton>}
          />
          <h2 className="mb-2 text-sm font-semibold text-muted">Care-plan history</h2>
          {patient.orders.length === 0 ? (
            <EmptyState title="No care plans for this patient yet" />
          ) : (
            <Card className="overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
                    <th className="px-4 py-3 font-semibold">#</th>
                    <th className="px-4 py-3 font-semibold">Medication</th>
                    <th className="px-4 py-3 font-semibold">Status</th>
                    <th className="px-4 py-3 font-semibold">Created</th>
                  </tr>
                </thead>
                <tbody>
                  {patient.orders.map((o) => (
                    <tr key={o.id} className="border-b border-line/60 last:border-0 hover:bg-background">
                      <td className="px-4 py-3">
                        <Link href={`/orders/${o.id}`} className="font-medium text-accent hover:underline">
                          {o.id}
                        </Link>
                      </td>
                      <td className="px-4 py-3">{o.medication_name}</td>
                      <td className="px-4 py-3">
                        <StatusBadge status={o.status} />
                      </td>
                      <td className="px-4 py-3 text-muted">{new Date(o.created_at).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}
        </>
      ) : null}
    </div>
  );
}
