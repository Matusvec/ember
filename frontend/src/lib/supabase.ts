import { createClient } from "@supabase/supabase-js";

// Vite only exposes env vars prefixed with VITE_ to browser code.
// These are the public (anon) keys — safe to ship to the client.
// Never put SUPABASE_SERVICE_ROLE_KEY here; it bypasses Row Level Security.
export const supabase = createClient(
  import.meta.env.VITE_SUPABASE_URL,
  import.meta.env.VITE_SUPABASE_ANON_KEY
);
