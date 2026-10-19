import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';

import { cn } from '@/lib/utils';

const badgeVariants = cva('inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-px text-2xs', {
  variants: {
    variant: {
      default: 'border-border bg-muted text-muted-foreground',
      accent: 'border-transparent bg-accent text-accent-foreground',
      warning: 'border-transparent bg-warning-soft text-warning',
      destructive: 'border-transparent bg-destructive-soft text-destructive',
      success: 'border-transparent bg-success-soft text-success',
      ref: 'border-border bg-muted px-1.5 py-0 font-mono text-2xs text-muted-foreground',
    },
  },
  defaultVariants: { variant: 'default' },
});

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
