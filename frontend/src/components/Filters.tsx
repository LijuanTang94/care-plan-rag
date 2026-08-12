"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

const STATUSES = ["", "pending", "processing", "completed", "failed"];

export function Filters({ status, q }: { status?: string; q?: string }) {
  const router = useRouter();
  const [search, setSearch] = useState(q ?? "");

  const apply = (next: { status?: string; q?: string }) => {
    const params = new URLSearchParams();
    const s = next.status ?? status;
    const query = next.q ?? search;
    if (s) params.set("status", s);
    if (query) params.set("q", query);
    router.push(`/?${params.toString()}`);
  };

  return (
    <form
      className="mb-4 flex flex-wrap items-center gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        apply({});
      }}
    >
      <input
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search patient name…"
        className="w-56 rounded-lg border border-line bg-white px-3 py-1.5 text-sm outline-none focus:border-accent focus:ring-2 focus:ring-accent/15"
      />
      <select
        value={status ?? ""}
        onChange={(e) => apply({ status: e.target.value })}
        className="rounded-lg border border-line bg-white px-3 py-1.5 text-sm outline-none focus:border-accent"
      >
        {STATUSES.map((s) => (
          <option key={s} value={s}>
            {s === "" ? "All statuses" : s}
          </option>
        ))}
      </select>
      <button
        type="submit"
        className="rounded-lg bg-accent px-3.5 py-1.5 text-sm font-medium text-white hover:bg-accent-strong"
      >
        Apply
      </button>
      {(status || q) && (
        <button
          type="button"
          onClick={() => router.push("/")}
          className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm text-muted hover:bg-background"
        >
          Clear
        </button>
      )}
    </form>
  );
}
