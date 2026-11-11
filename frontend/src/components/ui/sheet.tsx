'use client';

import * as React from 'react';
import * as SheetPrimitive from '@radix-ui/react-dialog';
import { cva, type VariantProps } from 'class-variance-authority';
import { X } from 'lucide-react';

import { cn } from '@/lib/utils';

const Sheet = SheetPrimitive.Root;
const SheetTrigger = SheetPrimitive.Trigger;
const SheetClose = SheetPrimitive.Close;

const SheetTitle = React.forwardRef<React.ElementRef<typeof SheetPrimitive.Title>, React.ComponentPropsWithoutRef<typeof SheetPrimitive.Title>>(
  ({ className, ...props }, ref) => <SheetPrimitive.Title ref={ref} className={cn('pr-8 text-title font-semibold', className)} {...props} />,
);
SheetTitle.displayName = SheetPrimitive.Title.displayName;

const sheetVariants = cva(
  'fixed inset-y-0 z-50 flex flex-col bg-card shadow-lg transition ease-in-out data-[state=closed]:duration-200 data-[state=open]:duration-300 data-[state=open]:animate-in data-[state=closed]:animate-out',
  {
    variants: {
      side: {
        left: 'left-0 w-[min(300px,85vw)] border-r data-[state=closed]:slide-out-to-left data-[state=open]:slide-in-from-left',
        right: 'right-0 border-l data-[state=closed]:slide-out-to-right data-[state=open]:slide-in-from-right',
      },
    },
    defaultVariants: { side: 'left' },
  },
);

const RIGHT_WIDTH = {
  sm: 'w-[min(380px,100vw)]',
  md: 'w-[min(480px,100vw)]',
  lg: 'w-[min(600px,100vw)]',
  xl: 'w-[min(760px,100vw)]',
};

interface SheetContentProps extends React.ComponentPropsWithoutRef<typeof SheetPrimitive.Content>, VariantProps<typeof sheetVariants> {
  /** Width of a right sheet. */
  size?: keyof typeof RIGHT_WIDTH;
  /** A fixed close button over a scrolling body; off when the content brings its own. */
  closeButton?: boolean;
}

const SheetContent = React.forwardRef<React.ElementRef<typeof SheetPrimitive.Content>, SheetContentProps>(
  ({ side, size = 'md', closeButton = side === 'right', className, children, ...props }, ref) => (
    <SheetPrimitive.Portal>
      <SheetPrimitive.Overlay className='fixed inset-0 z-50 bg-black/35 data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:animate-in data-[state=open]:fade-in-0' />
      <SheetPrimitive.Content
        ref={ref}
        aria-describedby={undefined}
        className={cn(sheetVariants({ side }), side === 'right' && RIGHT_WIDTH[size], className)}
        {...props}>
        {closeButton ? (
          <>
            <div className='min-h-0 flex-1 overflow-y-auto'>{children}</div>
            <SheetPrimitive.Close className='absolute right-2 top-2 inline-flex size-8 items-center justify-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'>
              <X className='size-4' aria-hidden />
              <span className='sr-only'>닫기</span>
            </SheetPrimitive.Close>
          </>
        ) : (
          children
        )}
      </SheetPrimitive.Content>
    </SheetPrimitive.Portal>
  ),
);
SheetContent.displayName = SheetPrimitive.Content.displayName;

export { Sheet, SheetTrigger, SheetClose, SheetContent, SheetTitle };
