export function BackendError({ message }: { message: string }) {
  return (
    <div className="rounded-xl border border-rose-200 bg-rose-50 px-5 py-4 text-sm text-rose-800">
      <p className="font-semibold">Couldn’t reach the backend</p>
      <p className="mt-1 text-rose-700">{message}</p>
      <p className="mt-2 text-xs text-rose-600">
        Start the API and database:{" "}
        <code className="rounded bg-rose-100 px-1 py-0.5 font-mono">docker compose up -d</code>{" "}
        (or run uvicorn locally on port 8000).
      </p>
    </div>
  );
}
