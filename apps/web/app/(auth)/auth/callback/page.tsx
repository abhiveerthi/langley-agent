"use client";

/**
 * Auth callback — handles BOTH Supabase Auth flows:
 *
 *   - Code flow (OAuth providers, signed-in via Google/GitHub/etc.):
 *       URL ends with `?code=<auth_code>`. We call exchangeCodeForSession.
 *
 *   - Implicit flow (invite + magic link signups):
 *       URL ends with `#access_token=...&refresh_token=...` in the fragment.
 *       Browsers never send fragments to the server, so this can't be a
 *       route.ts — has to be a Client Component. The Supabase JS SDK
 *       auto-detects the fragment and calls setSession internally; we
 *       just wait for the SIGNED_IN event before continuing.
 *
 * If `?org_invite_id=<uuid>` is present, we additionally call
 *   POST /api/invites/{id}/complete
 * which inserts the org_members row with role='limited' and marks the
 * invite accepted, so the new user lands inside the inviting workspace
 * instead of getting auto-provisioned a separate personal one.
 */

import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Loader2, AlertCircle } from "lucide-react";
import { createClient } from "@/lib/supabase/client";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type Phase = "running" | "error";

export default function AuthCallbackPage() {
  const router = useRouter();
  const params = useSearchParams();
  const ranOnce = useRef(false);
  const [phase, setPhase] = useState<Phase>("running");
  const [errorMsg, setErrorMsg] = useState<string>("");

  useEffect(() => {
    if (ranOnce.current) return;
    ranOnce.current = true;

    (async () => {
      const supabase = createClient();
      const orgInviteId = params.get("org_invite_id");
      const code = params.get("code");
      const next = params.get("next") ?? "/app/chat";

      // Step 1 — establish a session.
      try {
        if (code) {
          // Code flow: explicit exchange.
          const { error } = await supabase.auth.exchangeCodeForSession(code);
          if (error) throw new Error(`session_exchange: ${error.message}`);
        } else if (typeof window !== "undefined" && window.location.hash) {
          // Implicit flow: tokens are in the URL fragment. Parse them
          // explicitly and call setSession — relying on the Supabase
          // SDK's auto-detection (`onAuthStateChange` waiting for
          // SIGNED_IN) is racy because INITIAL_SESSION fires immediately
          // with `null` if hash parsing hasn't completed yet.
          const hashParams = new URLSearchParams(window.location.hash.slice(1));
          const access_token = hashParams.get("access_token");
          const refresh_token = hashParams.get("refresh_token");
          const errorDescription = hashParams.get("error_description") || hashParams.get("error");
          if (errorDescription) {
            throw new Error(`auth_provider: ${errorDescription}`);
          }
          if (!access_token || !refresh_token) {
            throw new Error("missing_tokens_in_fragment");
          }
          const { error } = await supabase.auth.setSession({ access_token, refresh_token });
          if (error) throw new Error(`set_session: ${error.message}`);
          // Clean the fragment so a stray refresh doesn't try to re-set.
          if (window.history.replaceState) {
            const cleaned = window.location.pathname + window.location.search;
            window.history.replaceState(null, "", cleaned);
          }
        }
        // If neither code nor fragment, fall through. The session check
        // below will catch unauthenticated requests.
      } catch (e) {
        setErrorMsg((e as Error).message);
        setPhase("error");
        setTimeout(() => router.replace(`/login?auth_error=${encodeURIComponent((e as Error).message)}`), 1500);
        return;
      }

      // Step 2 — if this is an invite acceptance, finalize on the server.
      if (orgInviteId) {
        const { data: { session } } = await supabase.auth.getSession();
        if (!session?.access_token) {
          setErrorMsg("no_session_for_invite");
          setPhase("error");
          setTimeout(() => router.replace("/login?auth_error=no_session_for_invite"), 1500);
          return;
        }
        try {
          const resp = await fetch(`${API}/api/invites/${orgInviteId}/complete`, {
            method: "POST",
            headers: {
              Authorization: `Bearer ${session.access_token}`,
              "Content-Type": "application/json",
            },
            body: "{}",
          });
          if (!resp.ok) {
            const body = await resp.json().catch(() => ({}));
            const detail = typeof body?.detail === "string" ? body.detail : "invite_completion_failed";
            setErrorMsg(detail);
            setPhase("error");
            setTimeout(() => router.replace(`/login?auth_error=${encodeURIComponent(detail)}`), 2000);
            return;
          }
        } catch (e) {
          const msg = `invite_completion_network: ${(e as Error).message}`;
          setErrorMsg(msg);
          setPhase("error");
          setTimeout(() => router.replace(`/login?auth_error=${encodeURIComponent(msg)}`), 2000);
          return;
        }
      }

      // Step 3 — done. Land in the workspace.
      // Open-redirect guard: a bare `next.startsWith("/")` accepts
      // `//attacker.com` and `/\attacker.com` (browsers parse those as
      // protocol-relative URLs). Require single slash + non-slash +
      // non-backslash next character.
      const dest = /^\/[^/\\]/.test(next) ? next : "/app/chat";
      router.replace(dest);
    })();
  }, [params, router]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-6">
      <div className="flex flex-col items-center gap-3 text-center">
        {phase === "running" ? (
          <>
            <Loader2 className="h-6 w-6 animate-spin text-primary" />
            <p className="text-sm text-muted-foreground">Signing you in…</p>
          </>
        ) : (
          <>
            <AlertCircle className="h-6 w-6 text-rose-500" />
            <p className="text-sm font-medium text-foreground">Couldn&apos;t complete sign-in</p>
            <p className="max-w-md text-xs text-muted-foreground">{errorMsg}</p>
            <p className="text-xs text-muted-foreground">Redirecting to login…</p>
          </>
        )}
      </div>
    </div>
  );
}
