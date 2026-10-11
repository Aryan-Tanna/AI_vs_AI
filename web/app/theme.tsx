"use client";

import { useEffect, useState } from "react";

type Theme = "auto" | "light" | "dark";
const KEY = "lexarena-theme";

export function ThemeButton() {
  const [theme, setTheme] = useState<Theme>("auto");
  useEffect(() => {
    try {
      const saved = localStorage.getItem(KEY) as Theme | null;
      if (saved) setTheme(saved);
    } catch {
      // storage blocked: stay on auto
    }
  }, []);
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "auto") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    try {
      localStorage.setItem(KEY, theme);
    } catch {
      // not remembered; fine
    }
  }, [theme]);
  const next: Record<Theme, Theme> = { auto: "light", light: "dark", dark: "auto" };
  return (
    <button className="theme-btn" onClick={() => setTheme(next[theme])} title="Theme">
      {theme === "auto" ? "◐ auto" : theme === "light" ? "☀ light" : "☾ dark"}
    </button>
  );
}
