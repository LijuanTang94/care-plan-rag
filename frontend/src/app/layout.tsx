import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "Care Plan Platform",
  description:
    "Retrieval-grounded pharmacist care-plan generation — Next.js dashboard over a FastAPI/RAG backend.",
};

const NAV = [
  { href: "/", label: "Dashboard" },
  { href: "/orders/new", label: "New care plan" },
  { href: "/patients", label: "Patients" },
];

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <header className="border-b border-line bg-surface">
          <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-6 py-3">
            <Link href="/" className="flex items-center gap-2">
              <span className="text-base font-semibold tracking-tight">Care Plan Platform</span>
              <span className="rounded bg-accent px-1.5 py-0.5 text-[0.62rem] font-bold uppercase tracking-wider text-white">
                RAG
              </span>
            </Link>
            <nav className="flex items-center gap-1 text-sm">
              {NAV.map((n) => (
                <Link
                  key={n.href}
                  href={n.href}
                  className="rounded-md px-3 py-1.5 text-muted transition-colors hover:bg-background hover:text-foreground"
                >
                  {n.label}
                </Link>
              ))}
            </nav>
          </div>
        </header>
        <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-8">{children}</main>
        <footer className="border-t border-line bg-surface">
          <div className="mx-auto max-w-6xl px-6 py-4 text-xs text-muted">
            Async pipeline · pgvector + Elasticsearch hybrid retrieval · claim-level NLI eval ·
            demo UI
          </div>
        </footer>
      </body>
    </html>
  );
}
