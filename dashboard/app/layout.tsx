import "./globals.css";
import type { Metadata } from "next";
import { Inter } from "next/font/google";
import Sidebar from "../components/Sidebar";
import StatusClock from "../components/StatusClock";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });

export const metadata: Metadata = {
  title: "Store Intelligence",
  description: "Purplle Brigade Bangalore — CCTV + POS analytics",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={inter.variable}>
      <body className="font-sans">
        <Sidebar />
        <div className="pl-60">
          <header className="sticky top-0 z-10 flex h-14 items-center justify-between border-b border-border bg-bg/80 px-8 backdrop-blur">
            <span className="text-xs uppercase tracking-wider text-slate-500">
              Retail Analytics
            </span>
            <StatusClock />
          </header>
          <main className="mx-auto max-w-6xl animate-fade-in px-8 py-8">{children}</main>
        </div>
      </body>
    </html>
  );
}
