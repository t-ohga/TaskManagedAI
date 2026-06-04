import type { Metadata } from "next";
import type { ReactNode } from "react";

import "./globals.css";
import { Geist } from "next/font/google";
import { cn } from "@/lib/utils";
import { THEME_INIT_SCRIPT } from "@/lib/theme";

const geist = Geist({subsets:['latin'],variable:'--font-sans'});

export const metadata: Metadata = {
  title: "TaskManagedAI",
  description: "TaskManagedAI admin shell"
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    // M-2 (ADR-00047): suppressHydrationWarning は inline script が hydration 前に `.dark` を付ける
    // ため必須 (server は class を制御せず script が唯一の source、no-FOUC + mismatch 回避、R1 F-001)。
    <html lang="ja" className={cn("font-sans", geist.variable)} suppressHydrationWarning>
      <head>
        {/* FOUC 解消: first paint 前に localStorage + matchMedia で `.dark` を適用する blocking script。
            固定文字列 (lib/theme.ts、ユーザ入力なし)。 */}
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body>
        <div className="min-h-dvh bg-canvas text-ink">{children}</div>
      </body>
    </html>
  );
}

