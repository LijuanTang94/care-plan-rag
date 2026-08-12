"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";
import { createOrderAction, type NewOrderState } from "./actions";
import { Card, Field, inputClass } from "@/components/ui";
import type { NewOrderInput } from "@/lib/data";

const DEFAULTS: NewOrderInput = {
  patient_first_name: "A.",
  patient_last_name: "B.",
  referring_provider: "Dr. Smith",
  referring_provider_npi: "1234567890",
  patient_mrn: "000123",
  patient_dob: "1979-06-08",
  primary_diagnosis: "G70.00",
  medication_name: "IVIG",
  patient_records:
    "Generalized myasthenia gravis (AChR antibody positive). Neurology recommends IVIG.",
};

const initial: NewOrderState = { status: "idle" };

export function NewOrderForm() {
  const [state, formAction] = useActionState(createOrderAction, initial);
  const v = state.values ?? DEFAULTS;

  return (
    <Card className="p-6">
      <form action={formAction} className="space-y-5">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="First name">
            <input name="patient_first_name" defaultValue={v.patient_first_name} required className={inputClass} />
          </Field>
          <Field label="Last name">
            <input name="patient_last_name" defaultValue={v.patient_last_name} required className={inputClass} />
          </Field>
          <Field label="Referring provider">
            <input name="referring_provider" defaultValue={v.referring_provider} required className={inputClass} />
          </Field>
          <Field label="Provider NPI" hint="(10 digits)">
            <input
              name="referring_provider_npi"
              defaultValue={v.referring_provider_npi}
              inputMode="numeric"
              pattern="\d{10}"
              maxLength={10}
              title="NPI must be exactly 10 digits"
              required
              className={inputClass}
            />
          </Field>
          <Field label="Patient MRN" hint="(6 digits)">
            <input
              name="patient_mrn"
              defaultValue={v.patient_mrn}
              inputMode="numeric"
              pattern="\d{6}"
              maxLength={6}
              title="MRN must be exactly 6 digits"
              required
              className={inputClass}
            />
          </Field>
          <Field label="Patient DOB">
            <input type="date" name="patient_dob" defaultValue={v.patient_dob} required className={inputClass} />
          </Field>
          <Field label="Primary diagnosis" hint="(ICD-10)">
            <input name="primary_diagnosis" defaultValue={v.primary_diagnosis} required className={inputClass} />
          </Field>
          <Field label="Medication">
            <input name="medication_name" defaultValue={v.medication_name} required className={inputClass} />
          </Field>
          <div className="sm:col-span-2">
            <Field label="Patient records">
              <textarea
                name="patient_records"
                defaultValue={v.patient_records}
                rows={4}
                required
                className={inputClass}
              />
            </Field>
          </div>
        </div>

        {state.status === "error" ? (
          <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
            ❌ {state.message}
          </p>
        ) : null}

        {state.status === "warning" ? (
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-3 text-sm text-amber-900">
            <p className="font-medium">⚠️ {state.message}</p>
            <p className="mt-1 text-amber-800">Submit again to create it anyway.</p>
            {/* confirm=true is carried by a hidden input on the confirm submit */}
            <input type="hidden" name="confirm" value="true" />
          </div>
        ) : null}

        <div className="flex items-center gap-3">
          <SubmitButton needsConfirm={state.status === "warning"} />
          <span className="text-xs text-muted">
            Validated &amp; de-duplicated · generated asynchronously · grounded in retrieved guidelines
          </span>
        </div>
      </form>
    </Card>
  );
}

function SubmitButton({ needsConfirm }: { needsConfirm: boolean }) {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className="inline-flex items-center justify-center rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-strong disabled:opacity-50"
    >
      {pending ? "Submitting…" : needsConfirm ? "Confirm and create" : "Generate care plan"}
    </button>
  );
}
