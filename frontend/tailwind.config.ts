import type { Config } from 'tailwindcss';
import animate from 'tailwindcss-animate';

export default {
  darkMode: 'class',
  content: ['./src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        border: 'hsl(var(--border))',
        input: 'hsl(var(--input))',
        ring: 'hsl(var(--ring))',
        background: 'hsl(var(--background))',
        foreground: 'hsl(var(--foreground))',
        primary: { DEFAULT: 'hsl(var(--primary))', foreground: 'hsl(var(--primary-foreground))' },
        secondary: { DEFAULT: 'hsl(var(--secondary))', foreground: 'hsl(var(--secondary-foreground))' },
        muted: { DEFAULT: 'hsl(var(--muted))', foreground: 'hsl(var(--muted-foreground))' },
        accent: { DEFAULT: 'hsl(var(--accent))', foreground: 'hsl(var(--accent-foreground))' },
        destructive: { DEFAULT: 'hsl(var(--destructive))', foreground: 'hsl(var(--destructive-foreground))', soft: 'hsl(var(--destructive-soft))' },
        warning: { DEFAULT: 'hsl(var(--warning))', soft: 'hsl(var(--warning-soft))' },
        success: { DEFAULT: 'hsl(var(--success))', soft: 'hsl(var(--success-soft))' },
        info: { DEFAULT: 'hsl(var(--info))', soft: 'hsl(var(--info-soft))' },
        faint: 'hsl(var(--faint))',
        card: { DEFAULT: 'hsl(var(--card))', foreground: 'hsl(var(--card-foreground))' },
        popover: { DEFAULT: 'hsl(var(--popover))', foreground: 'hsl(var(--popover-foreground))' },
      },
      // One column width for settings, review and journal screens.
      maxWidth: { reading: '820px' },
      borderRadius: {
        lg: 'var(--radius)',
        md: 'calc(var(--radius) - 2px)',
        sm: 'calc(var(--radius) - 4px)',
      },
      // Six steps in use: xs 12 (secondary), ui 13 (dense controls and tables), sm 14 (body), title 16 (section), xl 20 (page), display 28 (key figures).
      fontSize: {
        ui: ['13px', '20px'],
        title: ['16px', '24px'],
        display: ['28px', '34px'],
      },
      fontFamily: {
        sans: ['var(--font-pretendard)', 'Pretendard', '-apple-system', 'BlinkMacSystemFont', 'Apple SD Gothic Neo', 'Malgun Gothic', 'Segoe UI', 'sans-serif'],
        mono: ['ui-monospace', 'SF Mono', 'Menlo', 'Consolas', 'monospace'],
      },
      keyframes: {
        blink: { '50%': { opacity: '0' } },
      },
      animation: {
        blink: 'blink 1s steps(2) infinite',
      },
    },
  },
  plugins: [animate],
} satisfies Config;
