"""
Ember backend — FastAPI entry point.

Exposes REST endpoints consumed by the React frontend.
The Supabase client here uses the anon key so it respects Row Level Security;
swap to SUPABASE_SERVICE_ROLE_KEY only for admin-level operations that bypass RLS.
"""

from fastapi import FastAPI
from dotenv import load_dotenv
import os
from supabase import create_client, Client

# Load variables from .env into the process environment before anything else
load_dotenv()

# Single shared Supabase client — safe to reuse across requests (it's stateless)
supabase: Client = create_client(
    os.environ["SUPABASE_URL"],
    os.environ["SUPABASE_ANON_KEY"],
)

app = FastAPI()


@app.get("/health")
def health():
    """Liveness probe — returns 200 when the server is up and accepting requests."""
    return {"status": "ok"}
