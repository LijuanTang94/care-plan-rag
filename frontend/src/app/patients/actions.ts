"use server";

import { revalidatePath } from "next/cache";
import { ApiError } from "@/lib/api";
import { createPatient } from "@/lib/data";

export interface NewPatientState {
  status: "idle" | "error" | "success";
  message?: string;
}

export async function createPatientAction(
  _prev: NewPatientState,
  formData: FormData,
): Promise<NewPatientState> {
  const get = (k: string) => String(formData.get(k) ?? "").trim();
  try {
    const p = await createPatient({
      first_name: get("first_name"),
      last_name: get("last_name"),
      mrn: get("mrn"),
      dob: get("dob"),
    });
    revalidatePath("/patients");
    return { status: "success", message: `Added ${p.first_name} ${p.last_name} (MRN ${p.mrn}).` };
  } catch (e) {
    if (e instanceof ApiError) return { status: "error", message: e.message };
    return { status: "error", message: "Backend unreachable" };
  }
}
