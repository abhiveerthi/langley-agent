import { NextResponse } from "next/server";

// TODO: re-enable Supabase OAuth callback
// import { createClient } from "@/lib/supabase/server";
// export async function GET(request: Request) {
//   const { searchParams, origin } = new URL(request.url);
//   const code = searchParams.get("code");
//   if (code) {
//     const supabase = await createClient();
//     await supabase.auth.exchangeCodeForSession(code);
//   }
//   return NextResponse.redirect(`${origin}/chat`);
// }

export async function GET(request: Request) {
  const { origin } = new URL(request.url);
  return NextResponse.redirect(`${origin}/chat`);
}
