import * as React from 'react';

import { cn } from '@/lib/utils';

export const fieldClassName =
  'w-full rounded-md border border-input bg-card px-2.5 py-1.5 text-[13px] text-foreground placeholder:text-faint focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50';

const Input = React.forwardRef<HTMLInputElement, React.ComponentProps<'input'>>(({ className, type, ...props }, ref) => (
  <input type={type} className={cn(fieldClassName, 'h-8', className)} ref={ref} {...props} />
));
Input.displayName = 'Input';

export { Input };
