/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        axew: {
          bg: '#0A0A0C',
          surface: '#111115',
          panel: '#16161B',
          border: '#22222A',
          borderLight: '#2E2E3A',
          accent: '#5B5BFF',
          accentHover: '#7070FF',
          accentSubtle: '#1A1A3E',
          text: '#E8E8F0',
          textMuted: '#6B6B7E',
          textDim: '#3E3E4E',
          timeline: '#0D0D10',
          playhead: '#FF4444',
          waveform: '#3D6B8A',
          clip: '#1E3A5F',
          clipBorder: '#2A5080',
          success: '#22C55E',
          warning: '#F59E0B',
          error: '#EF4444',
          ai: '#A855F7',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
      fontSize: {
        '2xs': ['10px', '14px'],
        xs: ['11px', '16px'],
        sm: ['12px', '18px'],
        base: ['13px', '20px'],
        md: ['14px', '20px'],
        lg: ['16px', '24px'],
      },
      borderRadius: {
        DEFAULT: '4px',
        sm: '2px',
        md: '6px',
        lg: '10px',
        xl: '14px',
      },
      boxShadow: {
        panel: '0 4px 24px rgba(0, 0, 0, 0.6)',
        glow: '0 0 20px rgba(91, 91, 255, 0.3)',
      },
      animation: {
        'fade-in': 'fadeIn 0.2s ease-out',
        'pulse-slow': 'pulse 3s ease-in-out infinite',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
      },
    },
  },
  plugins: [],
}
