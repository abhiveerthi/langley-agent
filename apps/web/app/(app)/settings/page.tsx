import { cookies } from "next/headers";
import { ThemeSwitcher } from "@/components/ThemeSwitcher";

export default async function AppearanceSettingsPage() {
  const cookieStore = await cookies();
  const theme = cookieStore.get("marcus-theme")?.value ?? "default";

  return (
    <div className="max-w-lg">
      <h1 className="text-xl font-semibold">Appearance</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        Customize the look and feel of Marcus.
      </p>

      <div className="mt-8 space-y-6">
        <div className="rounded-lg border border-border bg-card p-6">
          <h2 className="text-sm font-medium text-foreground">Color theme</h2>
          <p className="mt-1 mb-4 text-xs text-muted-foreground">
            Choose an accent color. Changes apply instantly.
          </p>
          <ThemeSwitcher initialTheme={theme} />
        </div>
      </div>
    </div>
  );
}
