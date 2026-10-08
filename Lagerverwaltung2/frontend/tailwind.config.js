/** @type {import('tailwindcss').Config} */
const v = (n) => `rgb(var(--${n}) / <alpha-value>)`;
module.exports = {
  content: ["../app/templates/**/*.html", "../app/routes/*.py", "../app/static/js/*.js"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        bg: v("bg"), surface: v("surface"), ink: v("ink"), muted: v("muted"), line: v("line"),
        nav: v("nav"), navink: v("navink"), tag: v("tag"), tagink: v("tagink"),
        primary: v("primary"), ok: v("ok"), warn: v("warn"), crit: v("crit"), soft: v("soft"),
      },
      fontFamily: {
        sans: ["Barlow", "Segoe UI", "Arial", "sans-serif"],
        cond: ["Barlow Semi Condensed", "Barlow", "Arial Narrow", "sans-serif"],
      },
    },
  },
};
