import { supabase } from "../lib/supabase";
import { Loader2, Mail, Flame } from "lucide-react";
import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

/**
 * Sign-in / sign-up card supporting two auth methods:
 *   1. GitHub OAuth (redirects away; lands on /auth/callback)
 *   2. Email + password (handled inline)
 *
 * The `?mode=signup` query param pre-selects the signup tab so the landing
 * page "Create account" button opens directly to the right form state.
 */
export function AuthCard() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  // Default mode comes from the URL so deep-links work (/auth?mode=signup)
  const [mode, setMode] = useState<"signin" | "signup">(
    searchParams.get("mode") === "signup" ? "signup" : "signin"
  );
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  /** Kicks off the GitHub OAuth flow. Supabase redirects back to /auth/callback. */
  async function handleGitHub() {
    setLoading(true);
    setError(null);
    const { error } = await supabase.auth.signInWithOAuth({
      provider: "github",
      options: {
        // Must match an allowed redirect URL in your Supabase project settings
        redirectTo: `${window.location.origin}/auth/callback`,
      },
    });
    if (error) {
      setError(error.message);
      setLoading(false);
    }
    // On success the browser navigates away — no further code runs here
  }

  /** Handles both sign-up and sign-in via email/password. */
  async function handleEmailSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setMessage(null);

    if (mode === "signup") {
      const { error } = await supabase.auth.signUp({
        email,
        password,
        options: { emailRedirectTo: `${window.location.origin}/auth/callback` },
      });
      if (error) setError(error.message);
      else setMessage("Check your email for a confirmation link.");
    } else {
      const { error, data } = await supabase.auth.signInWithPassword({ email, password });
      if (error) {
        setError(error.message);
      } else if (data.user) {
        // Ensure a row exists in the public `users` table.
        // Supabase auth.users and public.users are separate tables;
        // we keep them in sync manually here instead of using a DB trigger.
        const { data: existing } = await supabase
          .from("users")
          .select("id")
          .eq("id", data.user.id)
          .single();

        if (!existing) {
          await supabase.from("users").insert({
            id: data.user.id,
            display_name: data.user.user_metadata?.full_name ?? data.user.email,
          });
        }
        navigate("/dashboard");
        return;
      }
    }

    setLoading(false);
  }

  const isSignUp = mode === "signup";

  return (
    <section
      className="ember-card ember-fade-in"
      aria-labelledby="auth-title"
    >
      <header
        style={{
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          marginBottom: 24,
        }}
      >
        <div className="ember-logo" aria-hidden="true">
          <Flame size={24} strokeWidth={2.2} />
        </div>
        <h1
          id="auth-title"
          style={{
            marginTop: 14,
            marginBottom: 0,
            fontSize: 22,
            fontWeight: 700,
            letterSpacing: "-0.3px",
          }}
        >
          {isSignUp ? "Create your account" : "Welcome back"}
        </h1>
        <p
          style={{
            marginTop: 6,
            marginBottom: 0,
            fontSize: 14,
            color: "var(--ember-muted)",
            textAlign: "center",
          }}
        >
          {isSignUp ? "Sign up to start using Ember" : "Sign in to your Ember account"}
        </p>
      </header>

      <button
        type="button"
        onClick={handleGitHub}
        disabled={loading}
        className="ember-btn ember-btn-secondary"
        aria-label="Continue with GitHub"
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
          <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0024 12c0-6.63-5.37-12-12-12z" />
        </svg>
        Continue with GitHub
      </button>

      <div
        role="separator"
        aria-label="or sign in with email"
        style={{ display: "flex", alignItems: "center", gap: 12, margin: "18px 0" }}
      >
        <div style={{ flex: 1, height: 1, background: "var(--ember-border)" }} />
        <span style={{ fontSize: 12, color: "#9ca3af", letterSpacing: 0.4 }}>OR</span>
        <div style={{ flex: 1, height: 1, background: "var(--ember-border)" }} />
      </div>

      <form
        onSubmit={handleEmailSubmit}
        style={{ display: "flex", flexDirection: "column", gap: 12 }}
        noValidate
      >
        {/* Labels are visually hidden but present for screen readers */}
        <label htmlFor="email" className="sr-only">Email</label>
        <input
          id="email"
          name="email"
          type="email"
          autoComplete="email"
          placeholder="Email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          disabled={loading}
          className="ember-input"
        />

        <label htmlFor="password" className="sr-only">Password</label>
        <input
          id="password"
          name="password"
          type="password"
          // Hint to password managers whether to fill saved vs. generate new
          autoComplete={isSignUp ? "new-password" : "current-password"}
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          minLength={6}
          disabled={loading}
          className="ember-input"
        />

        <button
          type="submit"
          disabled={loading}
          className="ember-btn ember-btn-primary"
          style={{ marginTop: 4 }}
        >
          {loading ? (
            <Loader2 size={18} className="animate-spin" aria-hidden="true" />
          ) : (
            <Mail size={18} aria-hidden="true" />
          )}
          {loading ? "Please wait…" : isSignUp ? "Sign up" : "Sign in"}
        </button>
      </form>

      {/* aria-live ensures errors/messages are announced by screen readers */}
      <div aria-live="polite" aria-atomic="true">
        {error && (
          <p
            role="alert"
            style={{
              marginTop: 16,
              marginBottom: 0,
              padding: "10px 14px",
              borderRadius: 12,
              fontSize: 13,
              background: "#fef2f2",
              color: "#b91c1c",
              border: "1px solid #fecaca",
            }}
          >
            {error}
          </p>
        )}
        {message && (
          <p
            style={{
              marginTop: 16,
              marginBottom: 0,
              padding: "10px 14px",
              borderRadius: 12,
              fontSize: 13,
              background: "var(--ember-green-soft)",
              color: "var(--ember-green-dark)",
              border: "1px solid #bbf7d0",
            }}
          >
            {message}
          </p>
        )}
      </div>

      <p
        style={{
          marginTop: 22,
          marginBottom: 0,
          textAlign: "center",
          fontSize: 14,
          color: "var(--ember-muted)",
        }}
      >
        {isSignUp ? "Already have an account? " : "Don't have an account? "}
        <button
          type="button"
          onClick={() => {
            setMode(isSignUp ? "signin" : "signup");
            // Clear stale feedback when switching modes
            setError(null);
            setMessage(null);
          }}
          className="ember-btn-ghost"
        >
          {isSignUp ? "Sign in" : "Register"}
        </button>
      </p>
    </section>
  );
}
