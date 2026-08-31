/** Дизайн-токены в стиле uxera (shadcn/ui + динамический акцент + glass). */
module.exports = {
  darkMode: ["class"],
  content: ["./app/**/*.{js,jsx,ts,tsx}", "./components/**/*.{js,jsx,ts,tsx}"],
  theme: {
    extend: {
      colors: {
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: { DEFAULT: "hsl(var(--primary))", foreground: "hsl(var(--primary-foreground))" },
        secondary: { DEFAULT: "hsl(var(--secondary))", foreground: "hsl(var(--secondary-foreground))" },
        destructive: { DEFAULT: "hsl(var(--destructive))", foreground: "hsl(var(--destructive-foreground))" },
        muted: { DEFAULT: "hsl(var(--muted))", foreground: "hsl(var(--muted-foreground))" },
        accent: { DEFAULT: "hsl(var(--accent))", foreground: "hsl(var(--accent-foreground))" },
        card: { DEFAULT: "hsl(var(--card))", foreground: "hsl(var(--card-foreground))" },
        "theme-primary": {
          DEFAULT: "rgb(var(--uxera-accent-rgb) / 1)",
          10: "rgb(var(--uxera-accent-rgb) / 0.1)",
          20: "rgb(var(--uxera-accent-rgb) / 0.2)",
          50: "rgb(var(--uxera-accent-rgb) / 0.5)",
        },
        success: "rgb(var(--success-rgb) / 1)",
      },
      fontFamily: {
        sans: ["var(--font-geist-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["var(--font-geist-mono)", "ui-monospace", "monospace"],
      },
      borderRadius: { lg: "var(--radius)", md: "calc(var(--radius) - 2px)", sm: "calc(var(--radius) - 4px)" },
      backgroundImage: {
        "theme-gradient": "linear-gradient(135deg, var(--uxera-accent) 0%, var(--uxera-accent-dark) 100%)",
      },
      boxShadow: { "theme-glow": "0 0 24px rgb(var(--uxera-accent-rgb) / 0.25)" },
    },
  },
  plugins: [require("tailwindcss-animate")],
};
