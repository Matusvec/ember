import { Link } from "react-router-dom";
import { Flame, Scan, Move, Keyboard, Accessibility } from "lucide-react";

/** Feature pills shown in the capabilities grid. */
const features = [
  { Icon: Scan, label: "Auto-detects movement" },
  { Icon: Move, label: "Head & face control" },
  { Icon: Keyboard, label: "Full keyboard & mouse" },
];

/**
 * Public marketing landing page — the first screen unauthenticated visitors see.
 * Links to /auth?mode=signin and /auth?mode=signup to pre-select the right tab.
 */
export function Landing() {
  return (
    <main className="ember-landing" aria-labelledby="ember-title">
      <section
        style={{
          maxWidth: 460,
          width: "100%",
          textAlign: "center",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
        }}
      >
        <div className="ember-logo ember-fade-in" aria-hidden="true">
          <Flame size={28} strokeWidth={2.2} />
        </div>

        <span
          className="ember-fade-in-delay-1"
          style={{
            marginTop: 16,
            display: "inline-flex",
            alignItems: "center",
            gap: 6,
            padding: "4px 10px",
            borderRadius: 999,
            background: "var(--ember-green-soft)",
            color: "var(--ember-green-dark)",
            fontSize: 12,
            fontWeight: 600,
            letterSpacing: 0.2,
          }}
        >
          <Accessibility size={14} aria-hidden="true" />
          Accessibility layer
        </span>

        <h1
          id="ember-title"
          className="ember-fade-in-delay-1"
          style={{
            fontSize: 56,
            fontWeight: 700,
            letterSpacing: "-2px",
            color: "var(--ember-text)",
            margin: "12px 0 0",
            lineHeight: 1.05,
          }}
        >
          Ember
        </h1>

        <p
          className="ember-fade-in-delay-2"
          style={{
            marginTop: 10,
            fontSize: 17,
            lineHeight: 1.6,
            color: "var(--ember-muted)",
            maxWidth: 360,
          }}
        >
          Your body. Your controls. Your world.
          <br />
          A free, webcam-only input layer for everyone.
        </p>

        <ul
          className="ember-fade-in-delay-2"
          aria-label="Key capabilities"
          style={{
            marginTop: 16,
            display: "grid",
            gridTemplateColumns: "repeat(3, 1fr)",
            gap: 8,
            listStyle: "none",
            padding: 0,
            width: "100%",
          }}
        >
          {features.map(({ Icon, label }) => (
            <li key={label} className="ember-feature">
              <span className="ember-feature-icon" aria-hidden="true">
                <Icon size={18} />
              </span>
              <span
                style={{
                  fontSize: 12,
                  fontWeight: 500,
                  color: "var(--ember-muted)",
                  textAlign: "center",
                }}
              >
                {label}
              </span>
            </li>
          ))}
        </ul>

        <nav
          aria-label="Get started"
          className="ember-fade-in-delay-3"
          style={{
            marginTop: 20,
            display: "flex",
            flexDirection: "column",
            gap: 8,
            width: "100%",
            maxWidth: 280,
          }}
        >
          <Link to="/auth?mode=signin" className="ember-btn ember-btn-primary">
            Sign in
          </Link>
          <Link to="/auth?mode=signup" className="ember-btn ember-btn-secondary">
            Create account
          </Link>
        </nav>
      </section>
    </main>
  );
}
