"use server";

import { revalidatePath } from "next/cache";
import { ApiError } from "@/lib/api";
import { retryOrder } from "@/lib/data";

export async function retryOrderAction(id: number): Promise<{ ok: boolean; message?: string }> {
  try {
    await retryOrder(id);
    revalidatePath(`/orders/${id}`);
    return { ok: true };
  } catch (e) {
    if (e instanceof ApiError) return { ok: false, message: e.message };
    return { ok: false, message: "Backend unreachable" };
  }
}
