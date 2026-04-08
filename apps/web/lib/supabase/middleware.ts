import { NextResponse, type NextRequest } from "next/server";

// TODO: re-enable Supabase session middleware
// import { createServerClient } from "@supabase/ssr";
// export async function updateSession(request: NextRequest) { ... }

export async function updateSession(request: NextRequest) {
  return NextResponse.next({ request });
}
