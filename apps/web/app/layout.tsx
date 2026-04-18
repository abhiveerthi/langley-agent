import type { Metadata, Viewport } from "next";
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
  title: "Backroom — The AI production team every YouTuber wishes they could afford",
  description:
    "Four AI specialists running the back office of your YouTube channel — strategy, publishing, community, and sponsors. Early access open.",
};

export const viewport: Viewport = {
  themeColor: "#0a0a0a",
  width: "device-width",
  initialScale: 1,
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
