import { Link } from "react-router-dom";
import { Shell } from "@/components/Shell";

export default function Welcome() {
  return (
    <Shell>
      <div className="max-w-3xl mx-auto pt-24 text-center">
        <div className="inline-flex items-center gap-2 chip mb-8">
          <span className="h-2 w-2 rounded-full bg-ember animate-pulse-soft" />
          Setup
        </div>
        <h1 className="text-6xl font-semibold tracking-tight">
          Welcome to <span className="text-ember">Ember</span>
        </h1>
        <p className="mt-6 text-lg text-muted leading-relaxed">
          An adaptive input layer for your computer. We'll figure out how you like to
          interact — whatever you can do becomes how you control everything.
        </p>

        <div className="mt-14 flex items-center justify-center gap-3">
          <Link to="/discover" className="btn btn-primary text-base px-6 py-3.5">
            Start setup
            <span aria-hidden>→</span>
          </Link>
          <Link to="/practice" className="btn btn-ghost text-sm">
            Skip to practice
          </Link>
        </div>

        <p className="mt-10 text-xs text-dim">
          Uses your webcam locally. Nothing leaves this machine.
        </p>
      </div>
    </Shell>
  );
}
