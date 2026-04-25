import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url);
  const code = searchParams.get("code");
  const state = searchParams.get("state");
  const oauthError = searchParams.get("error");

  const redirectTo = (path: string) => NextResponse.redirect(`${origin}${path}`);

  if (oauthError) {
    return redirectTo(`/app/integrations?dropbox=error&reason=${encodeURIComponent(oauthError)}`);
  }
  if (!code || !state) {
    return redirectTo("/app/integrations?dropbox=error&reason=missing_params");
  }

  const supabase = await createClient();
  const { data: { session } } = await supabase.auth.getSession();
  if (!session) {
    return redirectTo(`/login?next=${encodeURIComponent("/app/integrations")}`);
  }

  const res = await fetch(`${API_URL}/api/integrations/dropbox/callback`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${session.access_token}`,
    },
    body: JSON.stringify({ code, state }),
  });

  if (!res.ok) {
    let reason = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (body?.detail) reason = String(body.detail);
    } catch {
      const text = await res.text().catch(() => "");
      if (text) reason = text.slice(0, 200);
    }
    return redirectTo(`/app/integrations?dropbox=error&reason=${encodeURIComponent(reason)}`);
  }

  return redirectTo("/app/integrations?dropbox=connected");
}
