import clsx from "clsx";

export function Meter({ value, max, active }: { value: number; max: number; active: boolean }) {
  const pct = Math.max(0, Math.min(1, value / Math.max(max, 1e-6)));
  return (
    <div className="meter-track">
      <div
        className={clsx(
          "meter-fill",
          active ? "bg-ok" : "bg-ember-deep/70"
        )}
        style={{ width: `${pct * 100}%` }}
      />
    </div>
  );
}

export function ProgressPill({ progress, tone = "ember" }: { progress: number; tone?: "ember" | "warn" | "ok" }) {
  const p = Math.max(0, Math.min(1, progress));
  const bg = tone === "warn" ? "bg-warn" : tone === "ok" ? "bg-ok" : "bg-ember";
  return (
    <div className="meter-track">
      <div className={clsx("meter-fill", bg)} style={{ width: `${p * 100}%` }} />
    </div>
  );
}
