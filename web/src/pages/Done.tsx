import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Shell } from "@/components/Shell";
import { launchRuntime, stopRuntime } from "@/lib/api";

export default function Done() {
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    launchRuntime()
      .then(() => setRunning(true))
      .catch((e) => setError(e?.message ?? "launch failed"));
  }, []);

  async function stop() {
    await stopRuntime();
    setRunning(false);
  }

  return (
    <Shell>
      <div className="max-w-xl mx-auto pt-24 text-center">
        <div className="mx-auto h-20 w-20 rounded-full bg-ok/20 flex items-center justify-center">
          <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="#7bd98a" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="20 6 9 17 4 12" />
          </svg>
        </div>
        <h1 className="mt-6 text-4xl font-semibold tracking-tight">You're set</h1>
        <p className="mt-3 text-muted">
          Ember is running in the background. Your webcam now drives your computer.
        </p>

        {error && <div className="mt-6 text-warn">{error}</div>}

        <div className="mt-10 flex items-center justify-center gap-3">
          {running ? (
            <button className="btn btn-ghost" onClick={stop}>Stop Ember</button>
          ) : (
            <button className="btn btn-primary" onClick={() => launchRuntime().then(() => setRunning(true))}>
              Start Ember
            </button>
          )}
          <Link to="/" className="btn btn-ghost">Redo setup</Link>
        </div>

        <p className="mt-12 text-xs text-dim">
          Close this window anytime — Ember keeps running. Re-open localhost:8000 to reconfigure.
        </p>
      </div>
    </Shell>
  );
}
