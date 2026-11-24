import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = {
  title: "StockMock Terminal — Indian F&O Strategy Builder & Simulator",
  description:
    "Zero-lag Indian F&O Strategy Builder and Option Simulator for NIFTY, BANKNIFTY, FINNIFTY, and SENSEX.",
};

const THEME_INIT_SCRIPT = `
(function() {
  try {
    var stored = localStorage.getItem("stockmock-theme");
    var theme = (stored === "dark" || stored === "light") ? stored : "light";
    var meta = document.querySelector('meta[name="color-scheme"]');
    if (meta) meta.setAttribute("content", theme);
    document.documentElement.classList.toggle("dark", theme === "dark");
    document.documentElement.dataset.theme = theme;
  } catch (e) {}
})();
`;

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" data-theme="light" suppressHydrationWarning>
      <head>
        <meta name="color-scheme" content="light dark" />
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="min-h-screen bg-[#f4f6f9] text-slate-900 antialiased selection:bg-blue-500/20 dark:bg-[#0b0f17] dark:text-slate-100 dark:selection:bg-blue-500/30">
        {children}
      </body>
    </html>
  );
}
