import type { Config } from 'tailwindcss';

/**
 * Colours are declared once, in `src/index.css`, as space-separated RGB
 * channels on `:root`, `[data-theme='dark']` and `[data-accent='…']`. Tailwind
 * only names them, so a theme or accent swap is a single attribute change with
 * no duplicated palette.
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
        high: channel('--c-surface-high'),
        ink: channel('--c-ink'),
        'ink-muted': channel('--c-ink-muted'),
        'ink-faint': channel('--c-ink-faint'),
        hairline: channel('--c-hairline'),
        'hairline-strong': channel('--c-hairline-strong'),
        accent: channel('--c-accent'),
        'accent-soft': channel('--c-accent-soft'),
        'on-accent': channel('--c-on-accent'),
        'accent-ink': channel('--c-accent-ink'),
        sage: channel('--c-sage'),
        'sage-ink': channel('--c-sage-ink'),
        terracotta: channel('--c-terracotta'),
        series: {
          1: channel('--c-series-1'),
          2: channel('--c-series-2'),
          3: channel('--c-series-3'),
          4: channel('--c-series-4'),
        },
      },
      backgroundColor: {
        'accent-wash': 'var(--c-accent-wash)',
        'sage-wash': 'var(--c-sage-wash)',
        'terracotta-wash': 'var(--c-terracotta-wash)',
      },
      /**
       * TWO corner radii, and only two: 3px for everything structural, 10px
       * for the few large overlays that need to read as a slab. The aliases
       * all collapse onto one of the pair, so a stray `rounded-xl` cannot
       * introduce a third.
       */
      borderRadius: {
        none: '0px',
        DEFAULT: 'var(--r-sm)',
        sm: 'var(--r-sm)',
        md: 'var(--r-sm)',
        lg: 'var(--r-lg)',
        xl: 'var(--r-lg)',
        '2xl': 'var(--r-lg)',
        '3xl': 'var(--r-lg)',
        full: '9999px',
      },
      fontFamily: {
        serif: ['Fraunces', 'Cormorant Garamond', 'Iowan Old Style', 'Georgia', 'serif'],
        sans: ['"Inter Tight"', 'Manrope', 'Inter', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      /**
       * Every line-height is a multiple of 4px, so stacked type lands on the
       * baseline grid without correction.
       */
      fontSize: {
        micro: ['0.6875rem', { lineHeight: '1rem', letterSpacing: '0.08em', fontWeight: '500' }],
        small: ['0.8125rem', { lineHeight: '1.25rem' }],
        body: ['0.9375rem', { lineHeight: '1.5rem' }],
        'body-serif': ['1.0625rem', { lineHeight: '1.875rem' }],
        h3: ['1.125rem', { lineHeight: '1.5rem', fontWeight: '500' }],
        h2: ['1.625rem', { lineHeight: '2rem' }],
        h1: ['2.375rem', { lineHeight: '2.75rem', letterSpacing: '-0.015em' }],
        display: ['3.5rem', { lineHeight: '3.75rem', letterSpacing: '-0.024em' }],
        figure: ['2.75rem', { lineHeight: '3rem', letterSpacing: '-0.014em' }],
      },
      borderColor: {
        DEFAULT: channel('--c-hairline'),
      },
      boxShadow: {
        /**
         * Ambient fill + key light, both warm-tinted, never coloured. Three
         * stops: contact, key, and the long ambient throw. The `-lift` pair
         * add the top-edge highlight as an inset, so a raised surface catches
         * light on its own edge instead of only casting below.
         */
        hairline: '0 0 0 1px var(--c-shadow-hairline)',
        soft: '0 1px 2px var(--c-shadow-a), 0 4px 12px -2px var(--c-shadow-b)',
        lifted:
          '0 1px 2px var(--c-shadow-a), 0 8px 24px -6px var(--c-shadow-b), 0 24px 56px -24px var(--c-shadow-c)',
        overlay:
          '0 2px 4px var(--c-shadow-a), 0 16px 40px -8px var(--c-shadow-b), 0 40px 80px -32px var(--c-shadow-c)',
        'soft-lift':
          'inset 0 1px 0 var(--c-lift), 0 1px 2px var(--c-shadow-a), 0 4px 12px -2px var(--c-shadow-b)',
      },
      transitionTimingFunction: {
        editorial: 'cubic-bezier(0.22, 0.61, 0.36, 1)',
      },
      transitionDuration: {
        hover: '240ms',
        micro: '300ms',
        reveal: '450ms',
        draw: '600ms',
      },
      keyframes: {
        sweep: {
          '0%': { transform: 'translateX(-100%)' },
          '100%': { transform: 'translateX(100%)' },
        },
        // The hero grid drifts by exactly one cell, so the loop is seamless.
        'grid-drift': {
          '0%': { transform: 'translate3d(0, 0, 0)' },
          '100%': { transform: 'translate3d(24px, 24px, 0)' },
        },
        'grid-drift-slow': {
          '0%': { transform: 'translate3d(0, 0, 0)' },
          '100%': { transform: 'translate3d(-120px, 120px, 0)' },
        },
        // The backend-status dot: a slow, soft breath, not a blink.
        'pulse-soft': {
          '0%, 100%': { opacity: '1', transform: 'scale(1)' },
          '50%': { opacity: '0.45', transform: 'scale(0.88)' },
        },
      },
      maxWidth: {
        canvas: '68rem',
        prose: '38rem',
      },
      spacing: {
        rail: '17rem',
        'rail-collapsed': '4rem',
        // The density-aware rhythm. See the RHYTHM block in index.css.
        section: 'var(--gap-section)',
        block: 'var(--gap-block)',
        group: 'var(--gap-group)',
        card: 'var(--pad-card)',
        'card-tight': 'var(--pad-card-tight)',
      },
      letterSpacing: {
        label: '0.14em',
      },
    },
  },
  plugins: [],
} satisfies Config;
