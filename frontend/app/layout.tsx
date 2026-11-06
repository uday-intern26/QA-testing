import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";
import { Shell } from "@/components/Shell";
import { ThemeProvider } from "@/components/ThemeProvider";

export const metadata: Metadata = {
  title: "AIJewel QA",
  description: "Unified AIJewel QA console for virtual try-on and contract-driven agentic API testing.",
};

const themeBootScript = `
(function () {
  try {
    var raw = localStorage.getItem("aijewel.qa.generalSettings");
    var theme = "dark";
    if (raw) {
      var parsed = JSON.parse(raw);
      if (parsed && parsed.appearance && parsed.appearance.theme) theme = parsed.appearance.theme;
    }
    var resolved = theme;
    if (theme === "system") {
      resolved = window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
    }
    document.documentElement.dataset.theme = resolved;
    document.documentElement.style.colorScheme = resolved;
    document.documentElement.classList.add(resolved);
  } catch (e) {
    document.documentElement.dataset.theme = "dark";
  }
})();
`;

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeBootScript }} />
      </head>
      <body>
        <ThemeProvider>
          <Shell>{children}</Shell>
        </ThemeProvider>
      </body>
    </html>
  );
}
