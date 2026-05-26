import type { Metadata } from "next";
import type { ReactNode } from "react";

import "./globals.css";
import { Geist } from "next/font/google";
import { cn } from "@/lib/utils";

const geist = Geist({subsets:['latin'],variable:'--font-sans'});

export const metadata: Metadata = {
  title: "TaskManagedAI",
  description: "TaskManagedAI admin shell"
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ja" className={cn("font-sans", geist.variable)}>
      <body>
        <div className="min-h-dvh bg-canvas text-ink">{children}</div>
      </body>
    </html>
  );
}

