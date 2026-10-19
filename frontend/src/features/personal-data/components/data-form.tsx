'use client';

import { type ReactNode, useState } from 'react';
import { Controller, useForm, useWatch } from 'react-hook-form';

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
import { ALL_DAY, type FormValues, hasAllDay, initialValues, toggleAllDayValue, toPayload } from '../utils/form-values';
import type { FieldSpec } from '../utils/schema-fields';
import type { RecordOption } from '../utils/record-options';
import { hasRecordChoices, RecordSelect } from './record-select';

export type FieldSuggestions = Record<string, string[] | { dependsOn: string; options: Record<string, string[]> }>;

interface Props {
  fields: FieldSpec[];
  labels?: Record<string, string>;
  enumLabels?: Record<string, string>;
  current?: Record<string, unknown>;
  recordChoices?: Record<string, RecordOption[]>;
  suggestions?: FieldSuggestions;
  /** Fields kept in the payload with their current value but not shown (internal IDs, request keys). */
  hidden?: string[];
  submitLabel: string;
  onSubmit: (payload: Record<string, unknown>) => Promise<unknown>;
  onCancel: () => void;
  /** Extra actions on the left of the submit row (e.g. delete). */
  extraActions?: ReactNode;
}

export function DataForm({
  fields,
  labels,
  enumLabels,
  current,
  recordChoices,
  suggestions,
  hidden,
  submitLabel,
  onSubmit,
  onCancel,
  extraActions,
}: Props) {
  const { register, control, handleSubmit, formState, getValues, setValue } = useForm<FormValues>({ defaultValues: initialValues(fields, current) });
  const values = useWatch({ control });
  const fieldSuggestions = Object.fromEntries(
    Object.entries(suggestions ?? {}).map(([name, config]) => [
      name,
      Array.isArray(config) ? config : (config.options[String(values[config.dependsOn] ?? '')] ?? []),
    ]),
  );
  const allDayForm = hasAllDay(fields);
  const allDayValue = useWatch({ control, name: ALL_DAY.flag });
  const allDay = allDayForm && Boolean(allDayValue);
  const flipAllDay = (next: boolean) => {
    setValue(ALL_DAY.start, toggleAllDayValue(String(getValues(ALL_DAY.start) ?? ''), next, '09:00'));
    setValue(ALL_DAY.end, toggleAllDayValue(String(getValues(ALL_DAY.end) || getValues(ALL_DAY.start) || ''), next, '10:00'));
  };
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
          if (hidden?.includes(f.name)) return null;
          const id = `f-${f.name}`;
          if (f.kind === 'boolean') {
            return (
              <Controller
                key={f.name}
                name={f.name}
                control={control}
                render={({ field }) => (
                  <label className='mt-[18px] inline-flex cursor-pointer select-none items-center gap-2'>
                    <Checkbox
                      checked={Boolean(field.value)}
                      onCheckedChange={v => {
                        field.onChange(v === true);
                        if (allDayForm && f.name === ALL_DAY.flag) flipAllDay(v === true);
                      }}
                    />
                    {labels?.[f.name] ?? fieldLabel(f.name)}
                  </label>
                )}
              />
            );
          }
          return (
            <div key={f.name} className={cn('flex flex-col gap-1', f.kind === 'longtext' && 'md:col-span-2')}>
              <Label htmlFor={id}>
                {allDay && f.name === ALL_DAY.start
                  ? '시작일'
                  : allDay && f.name === ALL_DAY.end
                    ? '마지막 날'
                    : (labels?.[f.name] ?? fieldLabel(f.name))}{' '}
                {(f.required || (allDay && f.name === ALL_DAY.end)) && <span className='text-destructive'>*</span>}
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
                <NativeSelect
                  id={id}
                  required={f.required}
                  {...register(f.name, {
                    onChange: () => {
                      for (const [name, config] of Object.entries(suggestions ?? {})) {
                        if (!Array.isArray(config) && config.dependsOn === f.name) setValue(name, '', { shouldDirty: true });
                      }
                    },
                  })}>
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
                  list={fieldSuggestions[f.name] ? `${id}-suggestions` : undefined}
                  type={
                    f.kind === 'date' || (allDay && (f.name === ALL_DAY.start || f.name === ALL_DAY.end))
                      ? 'date'
                      : f.kind === 'datetime'
                        ? 'datetime-local'
                        : 'text'
                  }
                  inputMode={f.kind === 'decimal' ? 'decimal' : f.kind === 'integer' ? 'numeric' : undefined}
                  pattern={f.kind === 'decimal' ? '-?[0-9]+(\\.[0-9]+)?' : f.kind === 'integer' ? '-?[0-9]+' : undefined}
                  maxLength={f.name === 'currency' || f.name === 'base' || f.name === 'quote' ? 3 : undefined}
                  {...register(f.name)}
                />
              )}
              {fieldSuggestions[f.name] && (
                <datalist id={`${id}-suggestions`}>
                  {fieldSuggestions[f.name].map(value => (
                    <option key={value} value={value} />
                  ))}
                </datalist>
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
      <div className='mt-2 flex items-center justify-end gap-2'>
        {extraActions && <div className='mr-auto flex items-center gap-1'>{extraActions}</div>}
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
