import type { Metadata } from "next";
import { Courier_Prime, Inter, Newsreader, Noto_Sans_Gurmukhi } from "next/font/google";
import { Providers } from "@/components/providers";
import { AppHeader } from "@/components/domain/app-header";
import "./globals.css";

const inter = Inter({ variable: "--font-inter", subsets: ["latin"], display: "swap" });
const newsreader = Newsreader({ variable: "--font-newsreader", subsets: ["latin"], display: "swap" });
const courier = Courier_Prime({ variable: "--font-courier-prime", subsets: ["latin"], weight: ["400", "700"], display: "swap" });
// Gurmukhi is rendered from this font on purpose: without it the adapted screenplay would fall back to a system face
const gurmukhi = Noto_Sans_Gurmukhi({ variable: "--font-noto-gurmukhi", subsets: ["gurmukhi", "latin"], display: "swap" });

export const metadata: Metadata = {
  title: "Screenplay Studio: cultural adaptation",
  description: "Re-create a screenplay inside an exact culture and dialect, with every decision explained and approved.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${inter.variable} ${newsreader.variable} ${courier.variable} ${gurmukhi.variable} h-full`}>
      <body className="flex min-h-full flex-col">
        <Providers>
          <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:m-2 focus:rounded-md focus:bg-card focus:px-3 focus:py-2 focus:shadow-lift">
            Skip to content
          </a>
          <AppHeader />
          <main id="main" className="flex-1">{children}</main>
        </Providers>
      </body>
    </html>
  );
}
