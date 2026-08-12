"use client";

import { useEffect, useRef, useState, useTransition } from "react";
import { StatusBadge } from "@/components/ui";
import { retryOrderAction } from "./actions";
import type { OrderStatus } from "@/lib/types";

const TERMINAL = new Set(["completed", "failed"]);

export function LiveStatus({
  id,
  initialStatus,
  initialPlan,
}: {
  id: number;
  initialStatus: string;
  initialPlan: string;
}) {
  const [status, setStatus] = useState(initialStatus);
  const [plan, setPlan] = useState(initialPlan);
  const [polls, setPolls] = useState(0);
  const [retryMsg, setRetryMsg] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (TERMINAL.has(status)) return;
    let cancelled = false;

    const poll = async () => {
      try {
        const res = await fetch(`/api/orders/${id}/status`, { cache: "no-store" });
        const data: OrderStatus = await res.json();
        if (cancelled) return;
        setPolls((n) => n + 1);
        setStatus(data.status);
        if (data.care_plan) setPlan(data.care_plan);
        if (!TERMINAL.has(data.status)) {
          timer.current = setTimeout(poll, 2500);
        }
      } catch {
        if (!cancelled) timer.current = setTimeout(poll, 4000);
      }
    };

    timer.current = setTimeout(poll, 1500);
    return () => {
      cancelled = true;
      if (timer.current) clearTimeout(timer.current);
    };
  }, [id, status]);

  const onRetry = () => {
    setRetryMsg(null);
    startTransition(async () => {
      const r = await retryOrderAction(id);
      if (r.ok) {
        setStatus("processing");
        setPlan("");
        setPolls(0);
      } else {
        setRetryMsg(r.message ?? "Retry failed");
      }
    });
  };

  const inProgress = !TERMINAL.has(status);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <StatusBadge status={status} />
        {inProgress ? (
          <span className="inline-flex items-center gap-2 text-sm text-muted">
            <Spinner /> Generating… polled {polls} time{polls === 1 ? "" : "s"}
          </span>
        ) : status === "completed" ? (
          <a
            href={`/api/orders/${id}/download`}
            className="inline-flex items-center rounded-lg border border-line bg-surface px-3 py-1.5 text-sm font-medium hover:bg-background"
          >
            Download .txt
          </a>
        ) : (
          <button
            onClick={onRetry}
            disabled={pending}
            className="inline-flex items-center rounded-lg bg-rose-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-rose-700 disabled:opacity-50"
          >
            {pending ? "Retrying…" : "Retry generation"}
          </button>
        )}
      </div>

      {retryMsg ? <p className="text-sm text-rose-700">{retryMsg}</p> : null}

      {status === "completed" && plan ? (
        <pre className="whitespace-pre-wrap rounded-xl border border-line bg-slate-50 p-4 text-sm leading-relaxed text-foreground">
          {plan}
        </pre>
      ) : status === "failed" ? (
        <p className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-800">
          Generation failed. You can retry it above.
        </p>
      ) : (
        <div className="space-y-2 rounded-xl border border-line bg-surface p-4">
          <SkeletonLine w="w-3/4" />
          <SkeletonLine w="w-full" />
          <SkeletonLine w="w-5/6" />
          <SkeletonLine w="w-2/3" />
        </div>
      )}
    </div>
  );
}

function Spinner() {
  return (
    <span className="inline-block size-3.5 animate-spin rounded-full border-2 border-accent/30 border-t-accent" />
  );
}

function SkeletonLine({ w }: { w: string }) {
  return <div className={`h-3 animate-pulse rounded bg-slate-200 ${w}`} />;
}
