import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Aegis Dashboard",
  description: "AI Inference Runtime Monitor — VRAM management and job queue observability",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body className="antialiased">
        {children}
      </body>
    </html>
  );
}
