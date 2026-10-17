'use client';

import { useTheme } from 'next-themes';
import { Toaster as Sonner } from 'sonner';

type ToasterProps = React.ComponentProps<typeof Sonner>;

const Toaster = ({ ...props }: ToasterProps) => {
  const { theme = 'system' } = useTheme();
  return (
    <Sonner
      theme={theme as ToasterProps['theme']}
      toastOptions={{
        classNames: {
          toast: 'group border-border bg-card text-foreground shadow-lg',
          description: 'text-muted-foreground',
        },
      }}
      {...props}
    />
  );
};

export { Toaster };
