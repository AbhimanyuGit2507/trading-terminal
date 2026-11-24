import type { ReactNode } from "react";

export const metadata = {
  title: "Trading Terminal — Indian F&O Strategy Builder",
  description: "1:1 StockMock Strategy Builder & Option Simulator",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
