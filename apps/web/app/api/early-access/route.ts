import { NextResponse } from "next/server";
import { createClient } from "@supabase/supabase-js";
import { headers } from "next/headers";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function adminClient() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  // Supports the new `sb_secret_*` name, the legacy `service_role` JWT names,
  // and the project's existing convention — whichever is set wins.
  const secretKey =
    process.env.SUPABASE_SECRET_KEY ||
    process.env.SUPABASE_SERVICE_ROLE_KEY ||
    process.env.SUPABASE_SERVICE_KEY;
  if (!url || !secretKey) return null;
  return createClient(url, secretKey, {
    auth: { persistSession: false, autoRefreshToken: false },
  });
}

export async function POST(req: Request) {
  let body: { email?: unknown; channel_url?: unknown };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON" }, { status: 400 });
  }

  const email = typeof body.email === "string" ? body.email.trim().toLowerCase() : "";
  const channelUrl =
    typeof body.channel_url === "string" && body.channel_url.trim().length > 0
      ? body.channel_url.trim()
      : null;

  if (!email || !EMAIL_RE.test(email) || email.length > 254) {
    return NextResponse.json({ error: "Please enter a valid email." }, { status: 400 });
  }
  if (channelUrl && channelUrl.length > 500) {
    return NextResponse.json({ error: "Channel URL is too long." }, { status: 400 });
  }

  const supabase = adminClient();
  if (!supabase) {
    console.error("[early-access] Supabase service role not configured");
    return NextResponse.json(
      { error: "Signups are temporarily offline. Please try again shortly." },
      { status: 503 }
    );
  }

  const hdrs = await headers();
  const ip =
    hdrs.get("x-forwarded-for")?.split(",")[0]?.trim() ||
    hdrs.get("x-real-ip") ||
    null;
  const userAgent = hdrs.get("user-agent") ?? null;
  const referrer = hdrs.get("referer") ?? null;

  const { error } = await supabase.from("early_access_signups").insert({
    email,
    channel_url: channelUrl,
    source: "landing",
    ip_address: ip,
    user_agent: userAgent,
    referrer,
  });

  if (error) {
    // Unique violation = already signed up. Treat as success.
    if (error.code === "23505") {
      return NextResponse.json({ ok: true, duplicate: true });
    }
    console.error("[early-access] insert failed", error);
    return NextResponse.json(
      { error: "We couldn't save your signup. Please try again." },
      { status: 500 }
    );
  }

  return NextResponse.json({ ok: true });
}
