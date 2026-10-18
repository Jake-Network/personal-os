'use client';

import { useState } from 'react';
import { Controller, useForm } from 'react-hook-form';

import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect } from '@/components/ui/native-select';
import { Textarea } from '@/components/ui/textarea';

import { errorMessage } from '@/api-client/api-error';
import { cn } from '@/lib/utils';

import { enumLabel, fieldLabel } from '../consts/resources';
import { type FormValues, initialValues, toPayload } from '../utils/form-values';
import type { FieldSpec } from '../utils/schema-fields';
import type { RecordOption } from '../utils/record-options';
import { hasRecordChoices, RecordSelect } from './record-select';

interface Props {
  fields: FieldSpec[];
  labels?: Record<string, string>;
  enumLabels?: Record<string, string>;
  current?: Record<string, unknown>;
  recordChoices?: Record<string, RecordOption[]>;
  submitLabel: string;
  onSubmit: (payload: Record<string, unknown>) => Promise<unknown>;
  onCancel: () => void;
}

export function DataForm({ fields, labels, enumLabels, current, recordChoices, submitLabel, onSubmit, onCancel }: Props) {
  const { register, control, handleSubmit, formState } = useForm<FormValues>({ defaultValues: initialValues(fields, current) });
  const [error, setError] = useState<string | null>(null);

  const submit = handleSubmit(async values => {
    setError(null);
    try {
      await onSubmit(toPayload(fields, values));
    } catch (e) {
      setError(errorMessage(e));
    }
  });

  return (
    <form onSubmit={submit} className='flex flex-col gap-2.5'>
      <div className='grid grid-cols-1 gap-3.5 md:grid-cols-2'>
        {fields.map(f => {
          const id = `f-${f.name}`;
          if (f.kind === 'boolean') {
            return (
              <Controller
                key={f.name}
                name={f.name}
                control={control}
                render={({ field }) => (
                  <label className='mt-[18px] inline-flex cursor-pointer select-none items-center gap-2'>
                    <Checkbox checked={Boolean(field.value)} onCheckedChange={v => field.onChange(v === true)} />
                    {labels?.[f.name] ?? fieldLabel(f.name)}
                  </label>
                )}
              />
            );
          }
          return (
            <div key={f.name} className={cn('flex flex-col gap-1', f.kind === 'longtext' && 'md:col-span-2')}>
              <Label htmlFor={id}>
                {labels?.[f.name] ?? fieldLabel(f.name)} {f.required && <span className='text-destructive'>*</span>}
              </Label>
              {hasRecordChoices(f.name) || recordChoices?.[f.name] ? (
                <Controller
                  name={f.name}
                  control={control}
                  render={({ field }) => (
                    <RecordSelect
                      id={id}
                      fieldName={f.name}
                      options={recordChoices?.[f.name]}
                      required={f.required}
                      name={field.name}
                      ref={field.ref}
                      value={String(field.value ?? '')}
                      onBlur={field.onBlur}
                      onChange={field.onChange}
                    />
                  )}
                />
              ) : f.kind === 'enum' ? (
                <NativeSelect id={id} required={f.required} {...register(f.name)}>
                  <option value='' disabled={f.required}>
                    선택
                  </option>
                  {f.options!.map(o => (
                    <option key={o} value={o}>
                      {enumLabels?.[o] ?? enumLabel(o)}
                    </option>
                  ))}
                </NativeSelect>
              ) : f.kind === 'longtext' ? (
                <Textarea id={id} {...register(f.name)} />
              ) : (
                <Input
                  id={id}
                  required={f.required}
                  type={f.kind === 'date' ? 'date' : f.kind === 'datetime' ? 'datetime-local' : 'text'}
                  inputMode={f.kind === 'decimal' ? 'decimal' : f.kind === 'integer' ? 'numeric' : undefined}
                  pattern={f.kind === 'decimal' ? '-?[0-9]+(\\.[0-9]+)?' : f.kind === 'integer' ? '-?[0-9]+' : undefined}
                  maxLength={f.name === 'currency' || f.name === 'base' || f.name === 'quote' ? 3 : undefined}
                  {...register(f.name)}
                />
              )}
            </div>
          );
        })}
      </div>
      {error && (
        <Alert variant='destructive' className='whitespace-pre-wrap'>
          {error}
        </Alert>
      )}
      <div className='flex justify-end gap-2'>
        <Button type='button' onClick={onCancel}>
          취소
        </Button>
        <Button type='submit' variant='primary' disabled={formState.isSubmitting}>
          {submitLabel}
        </Button>
      </div>
    </form>
  );
}
