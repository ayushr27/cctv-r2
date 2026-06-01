import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./lib/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        ink: "#0a0e1a",
        panel: "#141a2a",
        edge: "#222b40",
      },
    },
  },
  plugins: [],
};

export default config;
