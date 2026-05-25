/*
 * 模块描述：应用设置页，集中管理外观模式、自定义种子色和 Material You 占位状态。
 */

import React, { useEffect, useMemo, useState } from 'react';
import { ArrowLeft, Check, Clock3, ExternalLink, Info, Link2, Monitor, Moon, PackageCheck, Palette, RefreshCw, RotateCcw, Server, Settings, Smartphone, Sun } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { DEFAULT_SEED } from '../lib/palette';
import { useThemeContext, type ColorSource, type ThemeMode } from '../contexts/ThemeContext';
import { BUILD_INFO } from '../lib/buildInfo';
import { HoverInfo } from './HoverInfo';
import { BrandMark } from './Brand';

const MODE_OPTIONS: Array<{ value: ThemeMode; label: string; icon: React.ComponentType<{ size?: number; strokeWidth?: number }> }> = [
  { value: 'light', label: '浅色', icon: Sun },
  { value: 'system', label: '系统', icon: Monitor },
  { value: 'dark', label: '深色', icon: Moon },
];

const COLOR_PRESETS = [
  '#3b62b8',
  '#0f766e',
  '#b83280',
  '#d97706',
  '#7c3aed',
  '#2563eb',
  '#dc2626',
  '#16a34a',
];

const COLOR_SOURCE_LABEL: Record<ColorSource, string> = {
  default: '默认品牌色',
  custom: '自定义种子色',
  monet: 'Material You',
};

const isHexColor = (value: string) => /^#[0-9a-f]{6}$/i.test(value);

export const SettingsPage: React.FC = () => {
  const navigate = useNavigate();
  const {
    mode,
    colorSource,
    customSeed,
    resolvedTheme,
    monetStatus,
    monetError,
    isMonetAvailableOnPlatform,
    setMode,
    setColorSource,
    setCustomSeed,
    resetColors,
    refreshMonet,
  } = useThemeContext();
  const [seedDraft, setSeedDraft] = useState(customSeed);
  const seedValid = isHexColor(seedDraft);

  useEffect(() => {
    setSeedDraft(customSeed);
  }, [customSeed]);

  const monetDescription = useMemo(() => {
    if (!isMonetAvailableOnPlatform) return '需 Android 客户端';
    if (monetStatus === 'available') return '跟随系统壁纸';
    if (monetStatus === 'loading') return '正在读取系统色';
    if (monetStatus === 'unavailable') return '此设备不支持 Material You';
    if (monetStatus === 'error') return '读取系统色失败';
    return '跟随系统壁纸';
  }, [isMonetAvailableOnPlatform, monetStatus]);

  const applySeedDraft = () => {
    if (!seedValid) return;
    setCustomSeed(seedDraft);
    setColorSource('custom');
  };

  const sourceButtonClass = (source: ColorSource, disabled = false) => [
    'lawver-pressable flex min-h-[86px] min-w-0 flex-1 flex-col justify-between rounded-[var(--radius-md)] border px-4 py-3 text-left transition-colors',
    source === colorSource
      ? 'border-[var(--accent)] bg-[var(--accent-quiet)] text-[var(--fg-1)] shadow-[0_0_0_1px_var(--accent)]'
      : 'border-[var(--border-subtle)] bg-[var(--bg-surface)] text-[var(--fg-2)] hover:border-[var(--border-default)] hover:bg-[var(--bg-surface-2)]',
    disabled ? 'cursor-not-allowed opacity-60 hover:border-[var(--border-subtle)] hover:bg-[var(--bg-surface)]' : ''
  ].join(' ');

  return (
    <div className="flex min-h-[100dvh] flex-col bg-[var(--bg-app)] text-[var(--fg-1)]">
      <header className="lawver-topbar sticky top-0 z-30 flex shrink-0 items-center justify-between gap-3 border-b border-[var(--border-subtle)] bg-[var(--bg-app)] px-3 pb-2 pt-[calc(0.625rem+var(--safe-top))] sm:px-5 sm:pb-3 sm:pt-[calc(0.75rem+var(--safe-top))]">
        <div className="flex min-w-0 items-center gap-2">
          <HoverInfo label="返回" placement="bottom">
            <button
              onClick={() => navigate(-1)}
              className="lawver-pressable inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-[var(--fg-3)] transition-colors hover:bg-[rgba(20,23,31,0.06)] hover:text-[var(--fg-1)] dark:hover:bg-white/[0.06] sm:h-11 sm:w-11"
              aria-label="返回"
            >
              <ArrowLeft size={20} strokeWidth={2} />
            </button>
          </HoverInfo>
          <BrandMark className="hidden h-8 w-8 shrink-0 text-[var(--accent)] sm:block" />
          <div className="min-w-0">
            <h1 className="t-title-l truncate">设置</h1>
            <p className="truncate text-[12px] text-[var(--fg-3)]">Settings</p>
          </div>
        </div>
        <div className="hidden items-center gap-2 rounded-full border border-[var(--border-subtle)] bg-[var(--bg-surface)] px-3 py-1.5 text-[12px] text-[var(--fg-3)] sm:flex">
          <Settings size={14} strokeWidth={2} />
          {resolvedTheme === 'dark' ? '深色' : '浅色'} · {COLOR_SOURCE_LABEL[colorSource]}
        </div>
      </header>

      <main className="custom-scrollbar flex min-h-0 flex-1 overflow-y-auto px-4 py-5 pb-[calc(1.25rem+var(--safe-bottom))] sm:px-6 sm:py-8">
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-5">
          <section className="rounded-[var(--radius-lg)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-1)] sm:p-5">
            <div className="mb-4 flex items-center gap-3">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-[var(--accent-quiet)] text-[var(--accent)]">
                <Sun size={20} strokeWidth={2} />
              </span>
              <div>
                <h2 className="t-title-m">外观模式</h2>
                <p className="text-[13px] text-[var(--fg-3)]">浅色、深色或跟随系统。</p>
              </div>
            </div>
            <div className="grid grid-cols-3 gap-2 rounded-[var(--radius-lg)] bg-[var(--bg-inset)] p-1.5">
              {MODE_OPTIONS.map(option => {
                const Icon = option.icon;
                const active = mode === option.value;
                return (
                  <button
                    key={option.value}
                    onClick={() => setMode(option.value)}
                    className={`lawver-pressable flex h-12 items-center justify-center gap-2 rounded-[var(--radius-md)] text-sm font-medium transition-colors ${
                      active
                        ? 'bg-[var(--bg-surface)] text-[var(--accent)] shadow-[var(--shadow-1)]'
                        : 'text-[var(--fg-3)] hover:text-[var(--fg-1)]'
                    }`}
                  >
                    <Icon size={17} strokeWidth={2} />
                    {option.label}
                  </button>
                );
              })}
            </div>
          </section>

          <section className="rounded-[var(--radius-lg)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] p-4 shadow-[var(--shadow-1)] sm:p-5">
            <div className="mb-4 flex items-center gap-3">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[var(--radius-md)] bg-[var(--accent-quiet)] text-[var(--accent)]">
                <Palette size={20} strokeWidth={2} />
              </span>
              <div>
                <h2 className="t-title-m">配色来源</h2>
                <p className="text-[13px] text-[var(--fg-3)]">默认品牌、自定义种子色或 Android 动态色。</p>
              </div>
            </div>

            <div className="grid gap-2 sm:grid-cols-3">
              <button onClick={resetColors} className={sourceButtonClass('default')}>
                <span className="flex items-center justify-between gap-2">
                  <span className="font-medium">默认</span>
                  {colorSource === 'default' && <Check size={17} strokeWidth={2} className="text-[var(--accent)]" />}
                </span>
                <span className="text-[12px] text-[var(--fg-3)]">Lawver 司法蓝</span>
              </button>

              <button onClick={() => setColorSource('custom')} className={sourceButtonClass('custom')}>
                <span className="flex items-center justify-between gap-2">
                  <span className="font-medium">自定义</span>
                  {colorSource === 'custom' && <Check size={17} strokeWidth={2} className="text-[var(--accent)]" />}
                </span>
                <span className="text-[12px] text-[var(--fg-3)]">使用种子色生成全套色板</span>
              </button>

              <button
                onClick={() => {
                  if (!isMonetAvailableOnPlatform) return;
                  setColorSource('monet');
                  refreshMonet();
                }}
                className={sourceButtonClass('monet', !isMonetAvailableOnPlatform)}
                disabled={!isMonetAvailableOnPlatform}
              >
                <span className="flex items-center justify-between gap-2">
                  <span className="inline-flex items-center gap-2 font-medium">
                    <Smartphone size={16} strokeWidth={2} />
                    Material You
                  </span>
                  {colorSource === 'monet' && <Check size={17} strokeWidth={2} className="text-[var(--accent)]" />}
                </span>
                <span className="text-[12px] text-[var(--fg-3)]">{monetDescription}</span>
              </button>
            </div>

            {colorSource === 'custom' && (
              <div className="mt-4 rounded-[var(--radius-md)] border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] p-4">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
                  <label className="flex items-center gap-3">
                    <input
                      type="color"
                      value={seedValid ? seedDraft : DEFAULT_SEED}
                      onChange={event => {
                        setSeedDraft(event.target.value);
                        setCustomSeed(event.target.value);
                      }}
                      className="h-11 w-14 cursor-pointer rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-transparent p-1"
                      aria-label="自定义种子色"
                    />
                    <input
                      value={seedDraft}
                      onChange={event => setSeedDraft(event.target.value)}
                      onBlur={applySeedDraft}
                      onKeyDown={event => {
                        if (event.key === 'Enter') applySeedDraft();
                      }}
                      className={`h-11 w-36 rounded-[var(--radius-md)] border bg-[var(--bg-surface)] px-3 font-mono text-sm outline-none transition-colors ${
                        seedValid ? 'border-[var(--border-default)] focus:border-[var(--accent)]' : 'border-[var(--color-danger-500)]'
                      }`}
                      aria-label="十六进制颜色"
                    />
                  </label>
                  <div className="flex flex-wrap gap-2">
                    {COLOR_PRESETS.map(color => (
                      <button
                        key={color}
                        onClick={() => {
                          setSeedDraft(color);
                          setCustomSeed(color);
                        }}
                        className="lawver-pressable h-8 w-8 rounded-full border border-[var(--border-default)] shadow-[var(--shadow-1)]"
                        style={{ backgroundColor: color }}
                        aria-label={`选择 ${color}`}
                      />
                    ))}
                  </div>
                  <button
                    onClick={() => {
                      setSeedDraft(DEFAULT_SEED);
                      setCustomSeed(DEFAULT_SEED);
                    }}
                    className="lawver-pressable inline-flex h-10 items-center justify-center gap-2 rounded-[var(--radius-md)] px-3 text-sm font-medium text-[var(--fg-3)] transition-colors hover:bg-[var(--bg-inset)] hover:text-[var(--fg-1)]"
                  >
                    <RotateCcw size={15} strokeWidth={2} />
                    重置
                  </button>
                </div>
              </div>
            )}

            {colorSource === 'monet' && (
              <div className="mt-4 rounded-[var(--radius-md)] border border-[var(--border-subtle)] bg-[var(--bg-surface-2)] p-4 text-sm text-[var(--fg-2)]">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <div className="font-medium text-[var(--fg-1)]">
                      {monetStatus === 'available' ? '已跟随系统动态色' : monetDescription}
                    </div>
                    {monetError && <div className="mt-1 break-words text-[12px] text-[var(--fg-3)]">{monetError}</div>}
                  </div>
                  {isMonetAvailableOnPlatform && (
                    <button
                      onClick={refreshMonet}
                      className="md3-btn-tonal lawver-pressable shrink-0 px-3 py-2 text-sm"
                      disabled={monetStatus === 'loading'}
                    >
                      <RefreshCw size={15} strokeWidth={2} className={monetStatus === 'loading' ? 'animate-spin' : ''} />
                      重试
                    </button>
                  )}
                </div>
              </div>
            )}
          </section>

          <section className="overflow-hidden rounded-[var(--radius-lg)] border border-[var(--border-subtle)] bg-[var(--bg-surface)] shadow-[var(--shadow-1)]">
            <div className="flex items-start gap-4 p-4 sm:p-5">
              <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-[var(--accent-quiet)] text-[var(--accent)]">
                <Info size={21} strokeWidth={2} />
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex min-w-0 items-center justify-between gap-3">
                  <div className="min-w-0">
                    <h2 className="t-title-m truncate">{BUILD_INFO.appName}</h2>
                    <p className="mt-1 text-[13px] leading-5 text-[var(--fg-3)]">{BUILD_INFO.description}</p>
                  </div>
                  <BrandMark className="hidden h-10 w-10 shrink-0 text-[var(--accent)] sm:block" />
                </div>
              </div>
            </div>
            <div className="grid gap-0 border-t border-[var(--border-subtle)] sm:grid-cols-2">
              <div className="flex min-w-0 gap-3 border-b border-[var(--border-subtle)] p-4 sm:border-r">
                <PackageCheck size={17} strokeWidth={2} className="mt-0.5 shrink-0 text-[var(--accent)]" />
                <div className="min-w-0">
                  <div className="t-label-s t-weak">版本 (Version)</div>
                  <div className="mt-1 truncate text-sm font-medium text-[var(--fg-1)]">{BUILD_INFO.version}</div>
                </div>
              </div>
              <div className="flex min-w-0 gap-3 border-b border-[var(--border-subtle)] p-4">
                <Server size={17} strokeWidth={2} className="mt-0.5 shrink-0 text-[var(--accent)]" />
                <div className="min-w-0">
                  <div className="t-label-s t-weak">构建环境 (Env)</div>
                  <div className="mt-1 truncate text-sm font-medium text-[var(--fg-1)]">{BUILD_INFO.environment}</div>
                </div>
              </div>
              <div className="flex min-w-0 gap-3 border-b border-[var(--border-subtle)] p-4 sm:border-b-0 sm:border-r">
                <Clock3 size={17} strokeWidth={2} className="mt-0.5 shrink-0 text-[var(--accent)]" />
                <div className="min-w-0">
                  <div className="t-label-s t-weak">构建时间 (Build Time)</div>
                  <div className="mt-1 break-words font-mono text-sm text-[var(--fg-1)]">{BUILD_INFO.buildTime}</div>
                </div>
              </div>
              <div className="flex min-w-0 gap-3 p-4">
                <Link2 size={17} strokeWidth={2} className="mt-0.5 shrink-0 text-[var(--accent)]" />
                <div className="min-w-0">
                  <div className="t-label-s t-weak">项目地址 (Project Url)</div>
                  <a
                    href={BUILD_INFO.projectUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="mt-1 inline-flex min-w-0 max-w-full items-center gap-1.5 text-sm font-medium text-[var(--accent)] hover:underline"
                  >
                    <span className="truncate">{BUILD_INFO.projectUrl}</span>
                    <ExternalLink size={13} strokeWidth={2} className="shrink-0" />
                  </a>
                </div>
              </div>
            </div>
          </section>
        </div>
      </main>
    </div>
  );
};
