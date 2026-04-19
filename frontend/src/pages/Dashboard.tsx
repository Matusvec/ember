import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Flame, LogOut } from "lucide-react";
import { supabase } from "../lib/supabase";

/**
 * Protected dashboard page.
 *
 * Checks for an active session on mount; unauthenticated visitors are
 * immediately redirected to /auth. This is a client-side guard — the real
 * data protection lives in Supabase Row Level Security policies.
 */
export function Dashboard() {
  const navigate = useNavigate();
  const [email, setEmail] = useState<string | null>(null);

  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (!session) navigate("/auth");
      else setEmail(session.user.email ?? null);
    });
  }, [navigate]);

  /** Signs the user out of Supabase and returns them to the auth page. */
  async function signOut() {
    await supabase.auth.signOut();
    navigate("/auth");
  }

  return (
    <main
      className="ember-landing"
      aria-labelledby="dashboard-title"
    >
      <section
        className="ember-fade-in"
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 14,
          maxWidth: 420,
          width: "100%",
          textAlign: "center",
        }}
      >
        <div className="ember-logo" aria-hidden="true">
          <Flame size={24} strokeWidth={2.2} />
        </div>

        <h1
          id="dashboard-title"
          style={{
            fontSize: 28,
            fontWeight: 700,
            letterSpacing: "-0.5px",
            margin: 0,
          }}
        >
          Ember — Dashboard
        </h1>

        <p style={{ color: "var(--ember-muted)", margin: 0, fontSize: 15 }}>
          Signed in as <strong style={{ color: "var(--ember-text)" }}>{email ?? "…"}</strong>
        </p>

        <button
          onClick={signOut}
          className="ember-btn ember-btn-secondary"
          style={{ maxWidth: 220, marginTop: 8 }}
          aria-label="Sign out of Ember"
        >
          <LogOut size={16} aria-hidden="true" />
          Sign out
        </button>
      </section>
    </main>
  );
}
