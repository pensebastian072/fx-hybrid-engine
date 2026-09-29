// Fonts are bundled locally so builds work offline / behind firewalls
// (next/font/google downloads them at build time).
import localFont from 'next/font/local';

import { cn } from '@/lib/utils';

const fontSans = localFont({ src: './fonts/geist-latin-wght-normal.woff2', weight: '100 900', variable: '--font-sans', display: 'swap' });

const fontMono = localFont({ src: './fonts/geist-mono-latin-wght-normal.woff2', weight: '100 900', variable: '--font-mono', display: 'swap' });

const fontInstrument = localFont({ src: './fonts/instrument-sans-latin-wght-normal.woff2', weight: '100 900', variable: '--font-instrument', display: 'swap' });

const fontNotoMono = localFont({ src: './fonts/noto-sans-mono-latin-wght-normal.woff2', weight: '100 900', variable: '--font-noto-mono', display: 'swap' });

const fontMullish = localFont({ src: './fonts/mulish-latin-wght-normal.woff2', weight: '100 900', variable: '--font-mullish', display: 'swap' });

const fontInter = localFont({ src: './fonts/inter-latin-wght-normal.woff2', weight: '100 900', variable: '--font-inter', display: 'swap' });

const fontArchitectsDaughter = localFont({ src: './fonts/architects-daughter-latin-400-normal.woff2', weight: '400', variable: '--font-architects-daughter', display: 'swap' });

const fontDMSans = localFont({ src: './fonts/dm-sans-latin-wght-normal.woff2', weight: '100 900', variable: '--font-dm-sans', display: 'swap' });

const fontFiraCode = localFont({ src: './fonts/fira-code-latin-wght-normal.woff2', weight: '100 900', variable: '--font-fira-code', display: 'swap' });

const fontOutfit = localFont({ src: './fonts/outfit-latin-wght-normal.woff2', weight: '100 900', variable: '--font-outfit', display: 'swap' });

const fontSpaceMono = localFont({ src: [{ path: './fonts/space-mono-latin-400-normal.woff2', weight: '400' }, { path: './fonts/space-mono-latin-700-normal.woff2', weight: '700' }], variable: '--font-space-mono', display: 'swap' });

export const fontVariables = cn(
  fontSans.variable,
  fontMono.variable,
  fontInstrument.variable,
  fontNotoMono.variable,
  fontMullish.variable,
  fontInter.variable,
  fontArchitectsDaughter.variable,
  fontDMSans.variable,
  fontFiraCode.variable,
  fontOutfit.variable,
  fontSpaceMono.variable
);
