import { BrowserRouter, Routes, Route } from "react-router-dom";
import { AuthCard } from "./components/AuthCard";
import { AuthCallback } from "./pages/AuthCallback";
import { Dashboard } from "./pages/Dashboard";
import { Landing } from "./pages/Landing";

/**
 * Root of the React app. Defines the four top-level routes:
 *   /              → marketing landing page
 *   /auth          → sign-in / sign-up form (AuthCard)
 *   /auth/callback → OAuth landing page; Supabase redirects here after GitHub login
 *   /dashboard     → protected page shown after successful auth
 */
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Landing />} />
        <Route
          path="/auth"
          element={
            // Wrap AuthCard in the same full-screen layout used by other pages
            <main className="ember-landing">
              <AuthCard />
            </main>
          }
        />
        <Route path="/auth/callback" element={<AuthCallback />} />
        <Route path="/dashboard" element={<Dashboard />} />
      </Routes>
    </BrowserRouter>
  );
}
