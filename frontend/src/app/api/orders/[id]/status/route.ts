import { NextResponse } from "next/server";
import { ApiError } from "@/lib/api";
import { getOrderStatus } from "@/lib/data";

// BFF proxy: client components poll this instead of the FastAPI backend directly,
// so the X-API-Key stays server-side.
export async function GET(_req: Request, ctx: RouteContext<"/api/orders/[id]/status">) {
  const { id } = await ctx.params;
  const orderId = Number(id);
  if (!Number.isFinite(orderId)) {
    return NextResponse.json({ message: "Invalid order id" }, { status: 400 });
  }
  try {
    const status = await getOrderStatus(orderId);
    return NextResponse.json(status);
  } catch (e) {
    if (e instanceof ApiError) {
      return NextResponse.json({ message: e.message, code: e.code }, { status: e.status });
    }
    return NextResponse.json({ message: "Backend unreachable" }, { status: 502 });
  }
}
