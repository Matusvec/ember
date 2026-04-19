import type { ReactNode } from "react";

export function Shell({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-full flex flex-col">
      <header className="flex items-center justify-between px-8 py-6">
        <div className="flex items-center gap-2.5">
          <div className="h-2.5 w-2.5 rounded-full bg-ember shadow-glow" />
          <span className="font-semibold tracking-tight text-text">Ember</span>
        </div>
        <span className="text-xs text-muted tracking-wide uppercase">adaptive control</span>
      </header>
      <main className="flex-1 px-8 pb-10 animate-fade-in">
        {children}
      </main>
    </div>
  );
}

export function StepDots({ total, current }: { total: number; current: number }) {
  return (
    <div className="flex items-center justify-center gap-2 py-4">
      {Array.from({ length: total }).map((_, i) => (
        <span
          key={i}
          className={[
            "h-1.5 rounded-full transition-all",
            i < current ? "w-6 bg-ember"
              : i === current ? "w-10 bg-ember"
              : "w-6 bg-border/60",
          ].join(" ")}
        />
      ))}
    </div>
  );
}
