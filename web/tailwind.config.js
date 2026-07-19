/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{vue,js,ts}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        canvas: '#0a0e14',
        surface: '#111722',
        'surface-2': '#161d2b',
        border: '#1f2937',
        accent: {
          DEFAULT: '#2dd4bf',
          soft: '#14b8a6',
          glow: '#5eead4',
        },
        healthy: '#34d399',
        degraded: '#fbbf24',
        critical: '#fb7185',
        info: '#60a5fa',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'monospace'],
      },
      boxShadow: {
        glow: '0 0 24px -4px rgba(45, 212, 191, 0.45)',
        'glow-critical': '0 0 24px -4px rgba(251, 113, 133, 0.45)',
        card: '0 1px 2px rgba(0,0,0,0.3), 0 8px 24px -12px rgba(0,0,0,0.5)',
      },
      keyframes: {
        pulseGlow: {
          '0%,100%': { opacity: '0.55' },
          '50%': { opacity: '1' },
        },
        fadeUp: {
          '0%': { opacity: '0', transform: 'translateY(6px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
      animation: {
        pulseGlow: 'pulseGlow 2.2s ease-in-out infinite',
        fadeUp: 'fadeUp 0.35s ease-out both',
      },
    },
  },
  plugins: [],
}
