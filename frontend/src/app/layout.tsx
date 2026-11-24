import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = {
  title: "StockMock Terminal — Indian F&O Strategy Builder & Simulator",
  description:
    "Zero-lag Indian F&O Strategy Builder and Option Simulator for NIFTY, BANKNIFTY, FINNIFTY, and SENSEX.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className="dark">
      <head>
        <meta name="color-scheme" content="dark light" />
      </head>
      <body className="min-h-screen bg-[#0b0f17] text-slate-100 antialiased selection:bg-blue-500/30">
        {children}
      </body>
    </html>
  );
}
