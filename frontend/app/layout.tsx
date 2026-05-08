import type { Metadata } from "next";
import type { ReactNode } from "react";

import "./globals.css";

export const metadata: Metadata = {
  title: "TaskManagedAI",
  description: "TaskManagedAI admin shell"
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ja">
      <body>
        <div className="min-h-dvh bg-canvas text-ink">{children}</div>
      </body>
    </html>
  );
}

