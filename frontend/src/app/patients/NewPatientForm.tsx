"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";
import { createPatientAction, type NewPatientState } from "./actions";
import { Card, Field, inputClass } from "@/components/ui";

const initial: NewPatientState = { status: "idle" };

export function NewPatientForm() {
  const [state, formAction] = useActionState(createPatientAction, initial);

  return (
    <Card className="p-5">
      <h2 className="mb-4 text-sm font-semibold">Add patient</h2>
      <form action={formAction} className="space-y-4">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <Field label="First name">
            <input name="first_name" required className={inputClass} />
          </Field>
          <Field label="Last name">
            <input name="last_name" required className={inputClass} />
          </Field>
          <Field label="MRN" hint="(6 digits)">
            <input name="mrn" inputMode="numeric" pattern="\d{6}" maxLength={6} required className={inputClass} />
          </Field>
          <Field label="DOB">
            <input type="date" name="dob" required className={inputClass} />
          </Field>
        </div>
        {state.status === "error" ? (
          <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-800">
            ❌ {state.message}
          </p>
        ) : null}
        {state.status === "success" ? (
          <p className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
            ✓ {state.message}
          </p>
        ) : null}
        <Submit />
      </form>
    </Card>
  );
}

function Submit() {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className="inline-flex items-center rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-strong disabled:opacity-50"
    >
      {pending ? "Adding…" : "Add patient"}
    </button>
  );
}
