// Typed data-access wrappers over the FastAPI backend (server-side only).
import "server-only";

import { apiFetch } from "./api";
import type {
  OrderAck,
  OrderBrief,
  OrderDetail,
  OrderStatus,
  Paginated,
  PatientBrief,
  PatientDetail,
} from "./types";

export interface ListOrdersParams {
  page?: number;
  page_size?: number;
  status?: string;
  patient_name?: string;
}

function qs(params: Record<string, string | number | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export function listOrders(p: ListOrdersParams = {}): Promise<Paginated<OrderBrief>> {
  return apiFetch(`/api/v1/orders${qs({ ...p })}`);
}

export function getOrder(id: number): Promise<OrderDetail> {
  return apiFetch(`/api/v1/orders/${id}`);
}

export function getOrderStatus(id: number): Promise<OrderStatus> {
  return apiFetch(`/api/v1/orders/${id}/status`);
}

export interface NewOrderInput {
  patient_first_name: string;
  patient_last_name: string;
  referring_provider: string;
  referring_provider_npi: string;
  patient_mrn: string;
  patient_dob: string;
  primary_diagnosis: string;
  medication_name: string;
  patient_records: string;
  confirm?: boolean;
}

export function createOrder(input: NewOrderInput): Promise<OrderAck> {
  return apiFetch(`/api/v1/orders`, { method: "POST", body: input });
}

export function retryOrder(id: number): Promise<{ order_id: number; status: string; message: string }> {
  return apiFetch(`/api/v1/orders/${id}/retry`, { method: "POST" });
}

export function listPatients(p: { page?: number; page_size?: number; search?: string } = {}): Promise<
  Paginated<PatientBrief>
> {
  return apiFetch(`/api/v1/patients${qs({ ...p })}`);
}

export function getPatient(id: number): Promise<PatientDetail> {
  return apiFetch(`/api/v1/patients/${id}`);
}

export function createPatient(input: {
  first_name: string;
  last_name: string;
  mrn: string;
  dob: string;
}): Promise<PatientBrief> {
  return apiFetch(`/api/v1/patients`, { method: "POST", body: input });
}
