import type { Metadata } from "next";
import { LocaleProvider } from "@/components/geode/locale-context";
import "./docs.css";

export const metadata: Metadata = {
  title: "GEODE Docs",
  description:
    "GEODE — General-Purpose Autonomous Execution Agent. Architecture, runtime, harness, and plugin documentation.",
};

export default function DocsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <LocaleProvider>{children}</LocaleProvider>;
}
