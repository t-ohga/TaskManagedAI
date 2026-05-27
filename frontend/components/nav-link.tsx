"use client";

import Link from "next/link";
import type { Route } from "next";
import { usePathname } from "next/navigation";

type NavLinkProps = {
  href: string;
  label: string;
};

export function NavLink({ href, label }: NavLinkProps) {
  const pathname = usePathname();
  const isActive = pathname === href || pathname.startsWith(href + "/");

  return (
    <Link
      aria-current={isActive ? "page" : undefined}
      className={
        isActive
          ? "block rounded-md bg-teal-50 px-3 py-2 text-sm font-semibold text-accent outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
          : "block rounded-md px-3 py-2 text-sm font-medium text-muted-foreground outline-offset-2 hover:bg-slate-50 hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
      }
      href={href as Route}
    >
      {label}
    </Link>
  );
}
