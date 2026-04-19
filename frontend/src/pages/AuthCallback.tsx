import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Loader2 } from "lucide-react";
import { supabase } from "../lib/supabase";

/**
 * Landing page for OAuth redirects (e.g. GitHub).
 *
 * Supabase appends a session fragment to the URL after the provider approves
 * the login. This component picks up that session, ensures the user has a row
 * in our public `users` table, then redirects to the dashboard.
 * If no session is found (e.g. the link expired) it sends the user back to /auth.
 */
export function AuthCallback() {
  const navigate = useNavigate();

  useEffect(() => {
    supabase.auth.getSession().then(async ({ data: { session } }) => {
      if (session?.user) {
        // OAuth users (GitHub etc.) arrive here for the first time without going
        // through AuthCard, so we upsert their public profile row here too.
        const { data: existing } = await supabase
          .from("users")
          .select("id")
          .eq("id", session.user.id)
          .single();

        if (!existing) {
          await supabase.from("users").insert({
            id: session.user.id,
            // Prefer GitHub display name → GitHub username → email address
            display_name:
              session.user.user_metadata?.full_name ??
              session.user.user_metadata?.login ??
              session.user.email,
          });
        }
        navigate("/dashboard");
      } else {
        navigate("/auth");
      }
    });
  }, [navigate]);

  return (
    <main
      className="ember-landing"
      role="status"
      aria-live="polite"
    >
      <div
        className="ember-fade-in"
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          color: "var(--ember-muted)",
          fontSize: 15,
        }}
      >
        <Loader2 size={18} className="animate-spin" aria-hidden="true" />
        Signing you in…
      </div>
    </main>
  );
}
