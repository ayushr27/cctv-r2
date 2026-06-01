import "./globals.css";
import Link from "next/link";

export const metadata = {
  title: "Store Intelligence",
  description: "Purplle Brigade Bangalore — CCTV + POS analytics",
};

const NAV = [
  { href: "/", label: "Live" },
  { href: "/funnel", label: "Funnel" },
  { href: "/anomalies", label: "Anomalies" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <header className="border-b border-edge bg-panel/60 backdrop-blur sticky top-0 z-10">
          <nav className="mx-auto max-w-6xl flex items-center gap-6 px-6 py-4">
            <span className="font-semibold tracking-tight text-slate-100">
              🛍️ Store Intelligence
            </span>
            <div className="flex gap-1">
              {NAV.map((n) => (
                <Link
                  key={n.href}
                  href={n.href}
                  className="px-3 py-1.5 rounded-md text-sm text-slate-300 hover:bg-edge hover:text-white transition-colors"
                >
                  {n.label}
                </Link>
              ))}
            </div>
            <span className="ml-auto text-xs text-slate-500">
              Brigade Bangalore · 10 Apr 2026
            </span>
          </nav>
        </header>
        <main className="mx-auto max-w-6xl px-6 py-8">{children}</main>
      </body>
    </html>
  );
}
