import React from 'react';

interface BrandMarkProps {
  className?: string;
}

export const BrandMark: React.FC<BrandMarkProps> = ({ className }) => {
  return (
    <svg className={className} viewBox="0 0 96 96" fill="none" aria-hidden="true">
      <rect x="0.5" y="0.5" width="95" height="95" rx="4.5" fill="var(--brand-logo-tile)" stroke="var(--brand-logo-border)" />
      <rect x="10.5" y="10.5" width="75" height="75" rx="2.5" stroke="var(--brand-logo-inner-border)" />
      <line x1="14" y1="78" x2="82" y2="78" stroke="var(--brand-logo-ink)" strokeWidth="0.75" strokeLinecap="round" opacity="0.55" />
      <g stroke="var(--brand-logo-ink)" strokeLinecap="round" strokeLinejoin="round" fill="none">
        <path
          d="M38 18 C38 18 36 20 36 26 L36 64 C36 70 38 72 42 72 L70 72"
          strokeWidth="2.2"
        />
        <path d="M30 18 L46 18" strokeWidth="1.2" />
        <path d="M70 70 L70 74" strokeWidth="1.2" />
        <circle cx="26" cy="82" r="1.2" fill="var(--brand-logo-ink)" stroke="none" />
        <circle cx="70" cy="82" r="1.2" fill="var(--brand-logo-ink)" stroke="none" />
      </g>
      <circle cx="50" cy="14" r="1.4" fill="var(--brand-logo-ink)" />
    </svg>
  );
};

interface BrandLockupProps {
  className?: string;
}

export const BrandLockup: React.FC<BrandLockupProps> = ({ className }) => (
  <div className={`flex items-center gap-3 ${className || ''}`} aria-label="Lawyance">
    <BrandMark className="h-10 w-10 shrink-0" />
    <span className="brand-wordmark">
      <span className="brand-wordmark-swash">L</span>awyance
    </span>
  </div>
);
