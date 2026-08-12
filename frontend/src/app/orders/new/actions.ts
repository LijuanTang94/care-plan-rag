"use server";

import { redirect } from "next/navigation";
import { ApiError } from "@/lib/api";
import { createOrder, type NewOrderInput } from "@/lib/data";

export interface NewOrderState {
  status: "idle" | "error" | "warning";
  message?: string;
  // Echo back the submitted values so the form (and the confirm resubmit) keep them.
  values?: NewOrderInput;
}

function readForm(formData: FormData): NewOrderInput {
  const get = (k: string) => String(formData.get(k) ?? "").trim();
  return {
    patient_first_name: get("patient_first_name"),
    patient_last_name: get("patient_last_name"),
    referring_provider: get("referring_provider"),
    referring_provider_npi: get("referring_provider_npi"),
    patient_mrn: get("patient_mrn"),
    patient_dob: get("patient_dob"),
    primary_diagnosis: get("primary_diagnosis"),
    medication_name: get("medication_name"),
    patient_records: get("patient_records"),
    confirm: formData.get("confirm") === "true",
  };
}

export async function createOrderAction(
  _prev: NewOrderState,
  formData: FormData,
): Promise<NewOrderState> {
  const values = readForm(formData);
  let ack;
  try {
    ack = await createOrder(values);
  } catch (e) {
    if (e instanceof ApiError) {
      // Backend WarningException (HTTP 200) → possible duplicate; let the user confirm.
      if (e.type === "warning") {
        return { status: "warning", message: e.message, values };
      }
      // validation (400) / block (409) / auth / unknown
      return { status: "error", message: e.message, values };
    }
    return { status: "error", message: "Could not reach the backend.", values };
  }
  // Success → go to the order detail page, which live-tracks generation.
  redirect(`/orders/${ack.id}`);
}
