import type {Metadata} from "next";import Link from "next/link";import "./globals.css";
export const metadata:Metadata={title:"Processing Diagnostics",description:"Video processing pipeline debugger"};
export default function RootLayout({children}:{children:React.ReactNode}){return <html lang="en"><body><header><strong>Processing Diagnostics</strong><Link href="/processing">New job</Link></header>{children}</body></html>}
