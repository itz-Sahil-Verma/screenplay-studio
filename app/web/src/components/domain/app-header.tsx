"use client";

import { Clapperboard, FolderKanban, PlayCircle, Plus } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Projects", icon: FolderKanban },
  { href: "/projects/demo", label: "Live demo", icon: PlayCircle },
];

export function AppHeader() {
  const path = usePathname();
  return (
    <header className="sticky top-0 z-40 border-b bg-paper/90 backdrop-blur supports-[backdrop-filter]:bg-paper/75">
      <div className="mx-auto flex h-14 max-w-7xl items-center gap-6 px-4 sm:px-6">
        <Link href="/" className="flex items-center gap-2.5">
          <span className="grid size-8 place-items-center rounded-lg bg-primary text-primary-foreground shadow-card">
            <Clapperboard className="size-4.5" aria-hidden />
          </span>
          <span className="font-heading text-lg font-medium tracking-tight">Screenplay Studio</span>
        </Link>
        <nav aria-label="Main" className="hidden items-center gap-1 sm:flex">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = href === "/" ? path === "/" : path.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn("flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium transition-colors",
                  active ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground")}
              >
                <Icon className="size-4" aria-hidden />
                {label}
              </Link>
            );
          })}
        </nav>
        <div className="ml-auto">
          <Link href="/new" className={buttonVariants({ size: "lg" })}>
            <Plus aria-hidden /> New adaptation
          </Link>
        </div>
      </div>
    </header>
  );
}
