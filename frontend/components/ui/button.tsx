// Copyright (c) 2026 Ramin Allazov (JavaAZE). All Rights Reserved.
import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg text-sm font-semibold ring-offset-[hsl(222_47%_4%)] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-realm-cyan focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-45 [&_svg]:size-4 [&_svg]:shrink-0',
  {
    variants: {
      variant: {
        primary:
          'bg-gradient-to-r from-realm-emerald to-realm-cyan text-[hsl(222_47%_6%)] shadow-glow-emerald transition-transform duration-150 hover:brightness-110 hover:shadow-[0_0_28px_hsl(var(--realm-emerald)/0.42)] active:scale-[0.98] active:brightness-95',
        glass: 'glass-panel text-zinc-100 hover:bg-white/10',
        ghost: 'text-zinc-200 hover:bg-white/5',
        danger:
          'bg-realm-crimson/90 text-white shadow-glow-crimson transition-transform duration-150 hover:bg-realm-crimson hover:shadow-[0_0_30px_hsl(var(--realm-crimson)/0.5)] active:scale-[0.98]',
        outline:
          'border border-white/15 bg-transparent text-zinc-100 transition-transform duration-150 hover:border-realm-cyan/50 hover:bg-realm-cyan/5 hover:shadow-glow-cyan active:scale-[0.98]',
      },
      size: {
        default: 'h-10 px-4 py-2',
        sm: 'h-8 rounded-md px-3 text-xs',
        lg: 'h-11 px-6 text-base',
        icon: 'size-10 rounded-lg',
      },
    },
    defaultVariants: {
      variant: 'primary',
      size: 'default',
    },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : 'button';
    return <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} {...props} />;
  }
);
Button.displayName = 'Button';

export { buttonVariants };
