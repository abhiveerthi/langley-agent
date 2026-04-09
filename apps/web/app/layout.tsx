import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { cookies } from "next/headers";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Marcus",
  description: "AI-powered creator platform",
};

const VALID_THEMES = ["default", "midnight", "ocean", "forest", "sunset", "rose", "gold"];

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const cookieStore = await cookies();
  const theme = cookieStore.get("marcus-theme")?.value ?? "default";
  const safeTheme = VALID_THEMES.includes(theme) ? theme : "default";

  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} dark`}
      data-theme={safeTheme}
    >
      <body className="min-h-screen bg-background text-foreground antialiased">
        {children}
      </body>
    </html>
  );
}
