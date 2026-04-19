/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg:      "#0b0a09",
        surface: "#15130f",
        card:    "#1e1a15",
        border:  "#3a3129",
        text:    "#f2ece4",
        muted:   "#a59589",
        dim:     "#5a4d42",
        ember:   "#f28b3a",
        "ember-soft": "#f9c18c",
        "ember-deep": "#b85d17",
        ok:      "#7bd98a",
        warn:    "#f2c04a",
      },
      fontFamily: {
        sans: [
          "Inter",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Helvetica Neue",
          "sans-serif",
        ],
      },
      boxShadow: {
        card: "0 10px 40px rgba(0,0,0,0.5), 0 1px 0 rgba(255,255,255,0.04) inset",
        glow: "0 0 0 6px rgba(242,139,58,0.14)",
      },
      keyframes: {
        fadeIn: {
          "0%": { opacity: "0", transform: "translateY(6px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        pulseSoft: {
          "0%, 100%": { opacity: "0.55" },
          "50%": { opacity: "1" },
        },
      },
      animation: {
        "fade-in":   "fadeIn 0.5s ease-out",
        "pulse-soft": "pulseSoft 1.6s ease-in-out infinite",
      },
    },
  },
  plugins: [],
};
