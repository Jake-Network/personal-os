'use client';

import { createContext, type ReactNode, useCallback, useContext, useRef, useState } from 'react';

import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';

export interface ConfirmOptions {
  title: string;
  /** What exactly is removed or changed, and what stays. */
  description?: ReactNode;
  confirmLabel?: string;
  destructive?: boolean;
}

type Confirm = (options: ConfirmOptions) => Promise<boolean>;

const ConfirmContext = createContext<Confirm | null>(null);

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [options, setOptions] = useState<ConfirmOptions | null>(null);
  const resolver = useRef<((ok: boolean) => void) | null>(null);

  const confirm = useCallback<Confirm>(next => {
    resolver.current?.(false);
    setOptions(next);
    return new Promise(resolve => {
      resolver.current = resolve;
    });
  }, []);

  const close = (ok: boolean) => {
    resolver.current?.(ok);
    resolver.current = null;
    setOptions(null);
  };

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}
      <Dialog open={!!options} onOpenChange={open => !open && close(false)}>
        <DialogContent className='w-[min(420px,calc(100%-32px))]' role='alertdialog'>
          <DialogHeader>
            <DialogTitle>{options?.title}</DialogTitle>
            {options?.description && <DialogDescription className='text-ui text-muted-foreground'>{options.description}</DialogDescription>}
          </DialogHeader>
          <div className='flex justify-end gap-2'>
            <Button onClick={() => close(false)}>취소</Button>
            <Button variant={options?.destructive ? 'destructive-solid' : 'primary'} autoFocus onClick={() => close(true)}>
              {options?.confirmLabel ?? '확인'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </ConfirmContext.Provider>
  );
}

/** Promise-based replacement for window.confirm with a described scope. */
export function useConfirm(): Confirm {
  const confirm = useContext(ConfirmContext);
  if (!confirm) throw new Error('useConfirm must be used inside ConfirmProvider');
  return confirm;
}
