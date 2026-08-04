import type { Metadata } from "next";
import { AppNav } from "@/components/AppNav";
import "./globals.css";

export const metadata: Metadata = {
  title: "Video Index",
  description: "Local multimodal video indexing and search workbench",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="en"><body><AppNav />{children}</body></html>;
}
