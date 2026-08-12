// TS mirrors of the FastAPI response shapes (careplan/schemas.py + main.py briefs).

export type CarePlanStatus = "pending" | "processing" | "completed" | "failed";

export interface OrderBrief {
  id: number;
  patient_name: string;
  medication_name: string;
  status: CarePlanStatus | string;
  created_at: string; // ISO
}

export interface OrderAck {
  id: number;
  careplan_id: number;
  patient_name: string;
  medication_name: string;
  status: string;
  message: string;
}

export interface OrderDetail {
  id: number;
  patient_name: string;
  medication_name: string;
  status: CarePlanStatus | string;
  care_plan: string;
}

export interface OrderStatus {
  id: number;
  status: CarePlanStatus | string;
  care_plan: string;
}

export interface PatientBrief {
  id: number;
  first_name: string;
  last_name: string;
  mrn: string;
  dob: string;
}

export interface PatientDetail extends PatientBrief {
  orders: OrderBrief[];
}

export interface Paginated<T> {
  count: number;
  page: number;
  page_size: number;
  results: T[];
}

// Unified error/warning envelope from careplan/exceptions.py: {type, code, message, detail}
export interface ApiEnvelope {
  type: "error" | "validation" | "block" | "warning" | "auth";
  code?: string;
  message: string;
  detail?: Record<string, unknown>;
}
