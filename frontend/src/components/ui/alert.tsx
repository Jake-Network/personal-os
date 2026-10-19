import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';

import { cn } from '@/lib/utils';

const alertVariants = cva('flex flex-wrap items-center gap-2.5 rounded-lg px-3.5 py-2.5 text-ui', {
  variants: {
    variant: {
      info: 'bg-info-soft text-foreground',
      warning: 'bg-warning-soft text-warning',
      destructive: 'bg-destructive-soft text-destructive',
      success: 'bg-success-soft text-success',
    },
  },
  defaultVariants: { variant: 'info' },
});

const Alert = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement> & VariantProps<typeof alertVariants>>(
  ({ className, variant, ...props }, ref) => <div ref={ref} role='alert' className={cn(alertVariants({ variant }), className)} {...props} />,
);
Alert.displayName = 'Alert';

export { Alert, alertVariants };
