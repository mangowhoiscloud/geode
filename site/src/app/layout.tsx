import type { Metadata } from "next";
import { Inter, Fira_Code, Outfit } from "next/font/google";
import "./globals.css";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

const outfit = Outfit({
  variable: "--font-display",
  subsets: ["latin"],
  weight: ["400", "600", "700", "800", "900"],
});

const firaCode = Fira_Code({
  variable: "--font-fira-code",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Jihwan Ryu — Portfolio",
  description:
    "GEODE · REODE · ECO2 — Agentic AI, Migration Harness, Distributed Systems",
  authors: [{ name: "Jihwan Ryu", url: "https://github.com/mangowhoiscloud" }],
  openGraph: {
    title: "Jihwan Ryu — Portfolio",
    description: "GEODE · REODE · ECO2",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko">
      <body
        className={`${inter.variable} ${outfit.variable} ${firaCode.variable} antialiased bg-[#0B1628] text-[#F0F0FF]`}
      >
        {children}
      </body>
    </html>
  );
}
