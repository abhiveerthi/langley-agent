import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";

export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url);
  const code = searchParams.get("code");
  const next = searchParams.get("next") ?? "/app/chat";

  const hasSupabase =
    !!process.env.NEXT_PUBLIC_SUPABASE_URL &&
    !!(process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY ||
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY);

  if (code && hasSupabase) {
    const supabase = await createClient();
    await supabase.auth.exchangeCodeForSession(code);
  }

  const dest = next.startsWith("/") ? next : "/app/chat";
  return NextResponse.redirect(`${origin}${dest}`);
}
