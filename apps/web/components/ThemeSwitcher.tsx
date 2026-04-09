"use client";

import { useState, useEffect } from "react";
import { cn } from "@/lib/utils";

export const THEMES = [
  {
    id: "default",
    label: "Default",
    bg: "#09090b",
    primary: "#6366f1",
  },
  {
    id: "midnight",
    label: "Midnight",
    bg: "#030307",
    primary: "#8b5cf6",
  },
  {
    id: "ocean",
    label: "Ocean",
    bg: "#040d12",
    primary: "#06b6d4",
  },
  {
    id: "forest",
    label: "Forest",
    bg: "#060d08",
    primary: "#10b981",
  },
  {
    id: "sunset",
    label: "Sunset",
    bg: "#0d0804",
    primary: "#f97316",
  },
  {
    id: "rose",
    label: "Rose",
    bg: "#0d0508",
    primary: "#f43f5e",
  },
  {
    id: "gold",
    label: "Gold",
    bg: "#0d0b04",
    primary: "#f59e0b",
  },
] as const;

type ThemeId = (typeof THEMES)[number]["id"];

function ThemeSwatch({
  theme,
  selected,
  onClick,
}: {
  theme: (typeof THEMES)[number];
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      title={theme.label}
      className={cn(
        "group flex flex-col items-center gap-2 rounded-lg p-2 transition-colors hover:bg-accent",
        selected && "bg-accent"
      )}
    >
      <div
        className={cn(
          "relative h-9 w-9 rounded-full border-2 transition-all",
          selected ? "border-primary scale-110 shadow-lg" : "border-border"
        )}
        style={{
          background: `linear-gradient(135deg, ${theme.bg} 50%, ${theme.primary} 50%)`,
        }}
      >
        {selected && (
          <span className="absolute inset-0 rounded-full ring-2 ring-primary ring-offset-2 ring-offset-background" />
        )}
      </div>
      <span
        className={cn(
          "text-xs transition-colors",
          selected ? "font-medium text-foreground" : "text-muted-foreground"
        )}
      >
        {theme.label}
      </span>
    </button>
  );
}

export function ThemeSwitcher({ initialTheme }: { initialTheme?: string }) {
  const [active, setActive] = useState<ThemeId>(
    (initialTheme as ThemeId) ?? "default"
  );

  useEffect(() => {
    const stored = document.cookie
      .split("; ")
      .find((c) => c.startsWith("marcus-theme="))
      ?.split("=")[1];
    if (stored) setActive(stored as ThemeId);
  }, []);

  function applyTheme(id: ThemeId) {
    setActive(id);
    document.documentElement.setAttribute("data-theme", id);
    const expires = new Date();
    expires.setFullYear(expires.getFullYear() + 1);
    document.cookie = `marcus-theme=${id}; path=/; expires=${expires.toUTCString()}; SameSite=Lax`;
  }

  return (
    <div className="flex flex-wrap gap-1">
      {THEMES.map((theme) => (
        <ThemeSwatch
          key={theme.id}
          theme={theme}
          selected={active === theme.id}
          onClick={() => applyTheme(theme.id)}
        />
      ))}
    </div>
  );
}
