import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}"
  ],
  theme: {
    extend: {
      colors: {
        canvas: "#f7f8fa",
        ink: "#17202a",
        muted: "#657083",
        line: "#d8dee8",
        panel: "#ffffff",
        accent: "#0f766e",
        attention: "#b45309",
        danger: "#b42318"
      }
    }
  },
  plugins: []
};

export default config;

