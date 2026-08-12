import { ApiError, apiFetch } from "@/lib/api";

// BFF proxy for the plain-text care-plan download (keeps the API key server-side).
export async function GET(_req: Request, ctx: RouteContext<"/api/orders/[id]/download">) {
  const { id } = await ctx.params;
  const orderId = Number(id);
  if (!Number.isFinite(orderId)) {
    return new Response("Invalid order id", { status: 400 });
  }
  try {
    const text = await apiFetch<string>(`/api/v1/orders/${orderId}/careplan/download`, {
      json: false,
    });
    return new Response(text, {
      headers: {
        "Content-Type": "text/plain; charset=utf-8",
        "Content-Disposition": `attachment; filename="careplan_order_${orderId}.txt"`,
      },
    });
  } catch (e) {
    const msg = e instanceof ApiError ? e.message : "Backend unreachable";
    const status = e instanceof ApiError ? e.status : 502;
    return new Response(msg, { status });
  }
}
