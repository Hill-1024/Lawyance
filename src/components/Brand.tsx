import React, { useId } from 'react';

interface BrandMarkProps {
  className?: string;
}

export const BrandMark: React.FC<BrandMarkProps> = ({ className }) => {
  const clipId = `lawyance-${useId().replace(/:/g, '')}`;

  return (
    <svg className={className} viewBox="0 0 64 64" fill="none" aria-hidden="true">
      <defs>
        <clipPath id={clipId}>
          <path d="M8 56 V28 a24 24 0 0 1 48 0 V56 Z" />
        </clipPath>
      </defs>
      <path d="M8 56 V28 a24 24 0 0 1 48 0 V56" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M4 56 H60" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
      <g clipPath={`url(#${clipId})`}>
        <path d="M40 18 V50" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
        <path d="M32 18 V50" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
        <path d="M40 18 H26 a8 8 0 0 0 0 16 H32" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
      </g>
    </svg>
  );
};

interface BrandLockupProps {
  className?: string;
}

export const BrandLockup: React.FC<BrandLockupProps> = ({ className }) => (
  <div className={`flex items-center gap-3 text-[var(--accent)] ${className || ''}`} aria-label="Lawyance">
    <BrandMark className="h-9 w-9 shrink-0" />
    <span className="font-serif text-[24px] font-medium leading-none text-[var(--fg-1)]">Lawyance</span>
  </div>
);
