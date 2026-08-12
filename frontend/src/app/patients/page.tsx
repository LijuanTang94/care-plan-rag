import Link from "next/link";
import { listPatients } from "@/lib/data";
import type { Paginated, PatientBrief } from "@/lib/types";
import { Card, EmptyState, PageHeader } from "@/components/ui";
import { BackendError } from "@/components/BackendError";
import { NewPatientForm } from "./NewPatientForm";

export const dynamic = "force-dynamic";
export const metadata = { title: "Patients · Care Plan Platform" };

export default async function PatientsPage() {
  let data: Paginated<PatientBrief> | null = null;
  let error: string | null = null;
  try {
    data = await listPatients({ page_size: 50 });
  } catch (e) {
    error = e instanceof Error ? e.message : "Failed to load patients";
  }

  return (
    <div>
      <PageHeader title="Patients" subtitle="Patient records and their care-plan history." />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1fr_320px]">
        <div>
          {error ? (
            <BackendError message={error} />
          ) : !data || data.results.length === 0 ? (
            <EmptyState title="No patients yet" hint="Add one with the form on the right." />
          ) : (
            <Card className="overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
                    <th className="px-4 py-3 font-semibold">Name</th>
                    <th className="px-4 py-3 font-semibold">MRN</th>
                    <th className="px-4 py-3 font-semibold">DOB</th>
                  </tr>
                </thead>
                <tbody>
                  {data.results.map((p) => (
                    <tr key={p.id} className="border-b border-line/60 last:border-0 hover:bg-background">
                      <td className="px-4 py-3">
                        <Link href={`/patients/${p.id}`} className="font-medium text-accent hover:underline">
                          {p.first_name} {p.last_name}
                        </Link>
                      </td>
                      <td className="px-4 py-3 font-mono text-xs">{p.mrn}</td>
                      <td className="px-4 py-3 text-muted">{p.dob || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}
        </div>
        <NewPatientForm />
      </div>
    </div>
  );
}
