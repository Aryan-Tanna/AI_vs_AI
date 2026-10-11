import "./globals.css";
import type { Metadata } from "next";
import { ThemeButton } from "./theme";

export const metadata: Metadata = {
  title: "LexArena Courtroom",
  description: "Live view of LexArena hearings: arguments, THEMIS checks, the bench and the verdict.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="topbar">
          <div className="topbar-inner">
            <a href="/" className="brand">
              ⚖ LexArena <small>courtroom</small>
            </a>
            <span className="spacer" />
            <ThemeButton />
          </div>
        </div>
        <div className="wrap">{children}</div>
      </body>
    </html>
  );
}
