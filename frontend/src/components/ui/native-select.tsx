import * as React from 'react';

import { cn } from '@/lib/utils';

import { fieldClassName } from './input';

/** Native <select>: keeps an empty "no value" option, which the Radix Select cannot represent. */
const NativeSelect = React.forwardRef<HTMLSelectElement, React.ComponentProps<'select'>>(({ className, ...props }, ref) => (
  <select className={cn(fieldClassName, 'h-8', className)} ref={ref} {...props} />
));
NativeSelect.displayName = 'NativeSelect';

export { NativeSelect };
