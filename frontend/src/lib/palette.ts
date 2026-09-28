/*
 * 模块描述：从种子色或 Monet 色板生成 Lawver 运行时 CSS 变量。
 */

import { argbFromHex, hexFromArgb, themeFromSourceColor } from '@material/material-color-utilities';

export type ResolvedTheme = 'light' | 'dark';
export type PaletteShade = 0 | 10 | 50 | 100 | 200 | 300 | 400 | 500 | 600 | 700 | 800 | 900 | 1000;
export type TonalPalette = Record<PaletteShade, string>;

export interface LawverPalette {
  primary: TonalPalette;
  secondary: TonalPalette;
  tertiary: TonalPalette;
  neutral: TonalPalette;
  neutralVariant: TonalPalette;
}

export interface MonetColors {
  accent1: Partial<Record<PaletteShade | string, string>>;
  accent2: Partial<Record<PaletteShade | string, string>>;
  accent3: Partial<Record<PaletteShade | string, string>>;
  neutral1: Partial<Record<PaletteShade | string, string>>;
  neutral2: Partial<Record<PaletteShade | string, string>>;
}

export const DEFAULT_SEED = '#3b62b8';

const SHADES = [0, 10, 50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 1000] as const;
const SHADE_TO_MATERIAL_TONE: Record<PaletteShade, number> = {
  0: 100,
  10: 99,
  50: 95,
  100: 90,
  200: 80,
  300: 70,
  400: 60,
  500: 40,
  600: 35,
  700: 30,
  800: 20,
  900: 10,
  1000: 0,
};

const DYNAMIC_CSS_VARIABLES = [
  '--brand-primary-50',
  '--brand-primary-100',
  '--brand-primary-200',
  '--brand-primary-300',
  '--brand-primary-400',
  '--brand-primary-500',
  '--brand-primary-600',
  '--brand-primary-700',
  '--brand-primary-800',
  '--brand-primary-900',
  '--brand-secondary-50',
  '--brand-secondary-100',
  '--brand-secondary-200',
  '--brand-secondary-300',
  '--brand-secondary-400',
  '--brand-secondary-500',
  '--brand-secondary-600',
  '--brand-secondary-700',
  '--brand-secondary-800',
  '--brand-secondary-900',
  '--brand-tertiary-50',
  '--brand-tertiary-100',
  '--brand-tertiary-200',
  '--brand-tertiary-300',
  '--brand-tertiary-400',
  '--brand-tertiary-500',
  '--brand-tertiary-600',
  '--brand-tertiary-700',
  '--brand-tertiary-800',
  '--neutral-0',
  '--neutral-25',
  '--neutral-50',
  '--neutral-100',
  '--neutral-200',
  '--neutral-300',
  '--neutral-400',
  '--neutral-500',
  '--neutral-600',
  '--neutral-700',
  '--neutral-800',
  '--neutral-900',
  '--neutral-950',
  '--bg-app',
  '--bg-surface',
  '--bg-surface-2',
  '--bg-elevated',
  '--bg-inset',
  '--fg-1',
  '--fg-2',
  '--fg-3',
  '--fg-4',
  '--border-subtle',
  '--border-default',
  '--border-strong',
  '--border-focus',
  '--accent',
  '--accent-hover',
  '--accent-quiet',
  '--accent-on',
] as const;

export const normalizeHexColor = (hex: string) => {
  const trimmed = hex.trim();
  if (/^#[0-9a-f]{6}$/i.test(trimmed)) return trimmed;
  if (/^[0-9a-f]{6}$/i.test(trimmed)) return `#${trimmed}`;
  return DEFAULT_SEED;
};

const rgba = (hex: string, alpha: number) => {
  const normalized = normalizeHexColor(hex).slice(1);
  const r = Number.parseInt(normalized.slice(0, 2), 16);
  const g = Number.parseInt(normalized.slice(2, 4), 16);
  const b = Number.parseInt(normalized.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
};

const paletteFromMaterial = (palette: { tone: (tone: number) => number }): TonalPalette => {
  const result = {} as TonalPalette;
  SHADES.forEach(shade => {
    result[shade] = hexFromArgb(palette.tone(SHADE_TO_MATERIAL_TONE[shade]));
  });
  return result;
};

const ensurePalette = (palette: Partial<Record<PaletteShade | string, string>>): TonalPalette => {
  const fallback = paletteFromSeed(DEFAULT_SEED).primary;
  const result = {} as TonalPalette;
  SHADES.forEach(shade => {
    const value = palette[shade] || palette[String(shade)];
    result[shade] = typeof value === 'string' ? normalizeHexColor(value) : fallback[shade];
  });
  return result;
};

export const paletteFromSeed = (seedHex: string): LawverPalette => {
  const theme = themeFromSourceColor(argbFromHex(normalizeHexColor(seedHex)));
  return {
    primary: paletteFromMaterial(theme.palettes.primary),
    secondary: paletteFromMaterial(theme.palettes.secondary),
    tertiary: paletteFromMaterial(theme.palettes.tertiary),
    neutral: paletteFromMaterial(theme.palettes.neutral),
    neutralVariant: paletteFromMaterial(theme.palettes.neutralVariant),
  };
};

export const paletteFromMonet = (monetColors: MonetColors): LawverPalette => ({
  primary: ensurePalette(monetColors.accent1),
  secondary: ensurePalette(monetColors.accent2),
  tertiary: ensurePalette(monetColors.accent3),
  neutral: ensurePalette(monetColors.neutral1),
  neutralVariant: ensurePalette(monetColors.neutral2),
});

const setColorScale = (
  root: HTMLElement,
  prefix: string,
  palette: TonalPalette,
  shades: readonly PaletteShade[]
) => {
  shades.forEach(shade => root.style.setProperty(`${prefix}-${shade}`, palette[shade]));
};

export const clearDynamicPalette = () => {
  const root = document.documentElement;
  DYNAMIC_CSS_VARIABLES.forEach(variable => root.style.removeProperty(variable));
};

export const applyPalette = (palette: LawverPalette, resolvedTheme: ResolvedTheme) => {
  const root = document.documentElement;

  setColorScale(root, '--brand-primary', palette.primary, [50, 100, 200, 300, 400, 500, 600, 700, 800, 900]);
  setColorScale(root, '--brand-secondary', palette.secondary, [50, 100, 200, 300, 400, 500, 600, 700, 800, 900]);
  setColorScale(root, '--brand-tertiary', palette.tertiary, [50, 100, 200, 300, 400, 500, 600, 700, 800]);

  root.style.setProperty('--neutral-0', palette.neutral[0]);
  root.style.setProperty('--neutral-25', palette.neutral[10]);
  root.style.setProperty('--neutral-50', palette.neutral[50]);
  root.style.setProperty('--neutral-100', palette.neutral[100]);
  root.style.setProperty('--neutral-200', palette.neutral[200]);
  root.style.setProperty('--neutral-300', palette.neutral[300]);
  root.style.setProperty('--neutral-400', palette.neutral[400]);
  root.style.setProperty('--neutral-500', palette.neutral[500]);
  root.style.setProperty('--neutral-600', palette.neutral[600]);
  root.style.setProperty('--neutral-700', palette.neutral[700]);
  root.style.setProperty('--neutral-800', palette.neutral[800]);
  root.style.setProperty('--neutral-900', palette.neutral[900]);
  root.style.setProperty('--neutral-950', palette.neutral[1000]);

  if (resolvedTheme === 'dark') {
    root.style.setProperty('--bg-app', palette.neutral[1000]);
    root.style.setProperty('--bg-surface', palette.neutral[900]);
    root.style.setProperty('--bg-surface-2', palette.neutral[800]);
    root.style.setProperty('--bg-elevated', palette.neutral[800]);
    root.style.setProperty('--bg-inset', palette.neutral[900]);
    root.style.setProperty('--fg-1', palette.neutral[100]);
    root.style.setProperty('--fg-2', palette.neutral[200]);
    root.style.setProperty('--fg-3', palette.neutralVariant[400]);
    root.style.setProperty('--fg-4', palette.neutralVariant[500]);
    root.style.setProperty('--border-subtle', rgba(palette.neutralVariant[200], 0.08));
    root.style.setProperty('--border-default', rgba(palette.neutralVariant[200], 0.12));
    root.style.setProperty('--border-strong', rgba(palette.neutralVariant[200], 0.2));
    root.style.setProperty('--border-focus', palette.primary[300]);
    root.style.setProperty('--accent', palette.primary[200]);
    root.style.setProperty('--accent-hover', palette.primary[300]);
    root.style.setProperty('--accent-quiet', rgba(palette.primary[800], 0.14));
    root.style.setProperty('--accent-on', palette.primary[900]);
    return;
  }

  root.style.setProperty('--bg-app', palette.neutral[50]);
  root.style.setProperty('--bg-surface', palette.neutral[0]);
  root.style.setProperty('--bg-surface-2', palette.neutral[10]);
  root.style.setProperty('--bg-elevated', palette.neutral[0]);
  root.style.setProperty('--bg-inset', palette.neutral[100]);
  root.style.setProperty('--fg-1', palette.neutral[900]);
  root.style.setProperty('--fg-2', palette.neutral[700]);
  root.style.setProperty('--fg-3', palette.neutralVariant[500]);
  root.style.setProperty('--fg-4', palette.neutralVariant[400]);
  root.style.setProperty('--border-subtle', rgba(palette.neutral[900], 0.06));
  root.style.setProperty('--border-default', rgba(palette.neutral[900], 0.1));
  root.style.setProperty('--border-strong', rgba(palette.neutral[900], 0.18));
  root.style.setProperty('--border-focus', palette.primary[500]);
  root.style.setProperty('--accent', palette.primary[500]);
  root.style.setProperty('--accent-hover', palette.primary[600]);
  root.style.setProperty('--accent-quiet', palette.primary[50]);
  root.style.setProperty('--accent-on', palette.neutral[0]);
};
