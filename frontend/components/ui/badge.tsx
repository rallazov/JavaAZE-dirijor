// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
import type { HTMLAttributes } from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

const badgeVariants = cva(
  'inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium uppercase tracking-wide',
  {
    variants: {
      variant: {
        safe: 'border-realm-emerald/40 bg-realm-emerald/10 text-realm-emerald',
        warn: 'border-realm-amber/45 bg-realm-amber/10 text-realm-amber',
        critical: 'border-realm-crimson/50 bg-realm-crimson/15 text-realm-crimson',
        neutral: 'border-white/10 bg-white/5 text-realm-muted',
      },
    },
    defaultVariants: { variant: 'neutral' },
  }
);

export interface BadgeProps extends HTMLAttributes<HTMLDivElement>, VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}
