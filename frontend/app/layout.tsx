import type { Metadata } from "next";
import { Providers } from "@/app/providers";
import { Inter } from "next/font/google";
import Script from "next/script";
import "./globals.css";

const inter = Inter({
  subsets: ["latin", "vietnamese"],
  variable: "--font-sans-override",
  display: "swap",
});

export const metadata: Metadata = {
  title: "AIRA",
  description: "Academic Integrity & Research Assistant",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="vi" className={inter.variable} suppressHydrationWarning>
      <body suppressHydrationWarning>
        <Script id="strip-extension-attrs" strategy="beforeInteractive">
          {`
            (() => {
              try {
                const ATTRS = [
                  "bis_skin_checked",
                  "data-gr-ext-installed",
                  "data-new-gr-c-s-check-loaded",
                ];
                const strip = () => {
                  for (const attr of ATTRS) {
                    document.querySelectorAll("[" + attr + "]").forEach((el) => {
                      try { el.removeAttribute(attr); } catch {}
                    });
                  }
                };
                strip();
                document.addEventListener("DOMContentLoaded", strip, { once: true });
                setTimeout(strip, 0);
                requestAnimationFrame(strip);
              } catch {}
            })();
          `}
        </Script>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
