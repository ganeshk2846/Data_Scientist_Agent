import type { Config } from 'tailwindcss';

/**
 * Colours are declared once, in `src/index.css`, as space-separated RGB
 * channels on `:root` and `[data-theme='dark']`. Tailwind only names them, so
 * a theme swap is a single class change with no duplicated palette.
 *
 * STRICT RULE: no purple, violet, lavender, indigo, magenta or pink may ever
 * enter this file. See CLAUDE.md.
 */
const channel = (name: string) => `rgb(var(${name}) / <alpha-value>)`;

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: ['class', "[data-theme='dark']"],
  theme: {
    extend: {
      colors: {
        bg: channel('--c-bg'),
        sunken: channel('--c-bg-sunken'),
        surface: channel('--c-surface'),
        raised: channel('--c-surface-raised'),
        ink: channel('--c-ink'),
        'ink-muted': channel('--c-ink-muted'),
        'ink-faint': channel('--c-ink-faint'),
        hairline: channel('--c-hairline'),
        'hairline-strong': channel('--c-hairline-strong'),
        gold: channel('--c-gold'),
        'gold-soft': channel('--c-gold-soft'),
        'on-gold': channel('--c-on-gold'),
        sage: channel('--c-sage'),
        terracotta: channel('--c-terracotta'),
        series: {
          1: channel('--c-series-1'),
          2: channel('--c-series-2'),
          3: channel('--c-series-3'),
          4: channel('--c-series-4'),
        },
      },
      backgroundColor: {
        'gold-wash': 'var(--c-gold-wash)',
        'sage-wash': 'var(--c-sage-wash)',
        'terracotta-wash': 'var(--c-terracotta-wash)',
      },
      fontFamily: {
        serif: ['Fraunces', 'Cormorant Garamond', 'Iowan Old Style', 'Georgia', 'serif'],
        sans: ['"Inter Tight"', 'Manrope', 'Inter', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      fontSize: {
        micro: ['0.6875rem', { lineHeight: '1rem', letterSpacing: '0.08em', fontWeight: '500' }],
        small: ['0.8125rem', { lineHeight: '1.25rem' }],
        body: ['0.9375rem', { lineHeight: '1.5rem' }],
        'body-serif': ['1.0625rem', { lineHeight: '1.875rem' }],
        h3: ['1.125rem', { lineHeight: '1.625rem', fontWeight: '500' }],
        h2: ['1.625rem', { lineHeight: '2.125rem' }],
        h1: ['2.375rem', { lineHeight: '2.75rem', letterSpacing: '-0.015em' }],
        display: ['3.5rem', { lineHeight: '3.75rem', letterSpacing: '-0.02em' }],
        figure: ['2.75rem', { lineHeight: '3rem', letterSpacing: '-0.01em' }],
      },
      borderColor: {
        DEFAULT: channel('--c-hairline'),
      },
      boxShadow: {
        // Layered and warm-tinted; never coloured glows.
        hairline: '0 0 0 1px var(--c-shadow-hairline)',
        soft: '0 1px 2px var(--c-shadow-a), 0 4px 12px -2px var(--c-shadow-b)',
        lifted: '0 1px 2px var(--c-shadow-a), 0 8px 24px -6px var(--c-shadow-b), 0 24px 56px -24px var(--c-shadow-c)',
        overlay: '0 2px 4px var(--c-shadow-a), 0 16px 40px -8px var(--c-shadow-b), 0 40px 80px -32px var(--c-shadow-c)',
      },
      transitionTimingFunction: {
        editorial: 'cubic-bezier(0.22, 0.61, 0.36, 1)',
      },
      transitionDuration: {
        micro: '300ms',
        reveal: '450ms',
        draw: '600ms',
      },
      keyframes: {
        sweep: {
          '0%': { transform: 'translateX(-100%)' },
          '100%': { transform: 'translateX(100%)' },
        },
      },
      maxWidth: {
        canvas: '68rem',
        prose: '38rem',
      },
      spacing: {
        rail: '17rem',
      },
    },
  },
  plugins: [],
} satisfies Config;
