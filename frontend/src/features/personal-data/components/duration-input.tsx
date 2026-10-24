import { forwardRef } from 'react';

import { Input } from '@/components/ui/input';

interface Props {
  id: string;
  value: string;
  label: string;
  onChange: (value: string) => void;
  onBlur: () => void;
}

/** Three keyboard- and pointer-adjustable parts backed by one seconds field. */
export const DurationInput = forwardRef<HTMLInputElement, Props>(({ id, value, label, onChange, onBlur }, ref) => {
  const parts = value ? value.split(':') : ['', '', ''];
  return (
    <div role='group' aria-label={label} className='flex gap-2'>
      {['시간', '분', '초'].map((unit, index) => (
        <label key={unit} className='flex min-w-0 flex-1 items-center gap-1 text-ui text-muted-foreground'>
          <Input
            id={index === 0 ? id : `${id}-${index}`}
            ref={index === 0 ? ref : undefined}
            type='number'
            inputMode='numeric'
            aria-label={`${label} ${unit}`}
            min={0}
            max={index === 0 ? undefined : 59}
            step={1}
            placeholder='0'
            value={parts[index] ?? ''}
            onBlur={onBlur}
            onChange={event => onChange(parts.map((part, i) => i === index ? event.target.value : part).join(':'))}
          />
          {unit}
        </label>
      ))}
    </div>
  );
});
DurationInput.displayName = 'DurationInput';
