'use client';

import { type ReactNode, useState } from 'react';

import { useMutation } from '@tanstack/react-query';
import { History, Trash2 } from 'lucide-react';

import { useConfirm } from '@/components/confirm-dialog';
import { notify } from '@/components/notify';
import { ListSkeleton } from '@/components/skeleton';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet';

import { RESOURCE_API, type Row } from '../api/resource-api';
import { RESOURCES } from '../consts/resources';
import { useInvalidateResource } from '../hooks/use-resource';
import { useSchemaFields } from '../hooks/use-schema-fields';
import type { RecordOption } from '../utils/record-options';
import { DataForm, type FieldSuggestions } from './data-form';
import { HISTORY_RESOURCES, ValueHistoryDialog } from './value-history-dialog';

export interface RecordSheetProps {
  resource: string;
  /** null opens an empty form; a row opens it for editing. */
  record: Row | null;
  open: boolean;
  onClose: () => void;
  /** Prefilled values for a new record (e.g. the day picked on a calendar). */
  defaults?: Record<string, unknown>;
  title?: string;
  /** One line above the form, e.g. why only the start date was used. */
  note?: ReactNode;
  labels?: Record<string, string>;
  hidden?: string[];
  recordChoices?: Record<string, RecordOption[]>;
  suggestions?: FieldSuggestions;
  onSaved?: (saved: unknown) => void;
  /** Read-only details shown above the form when editing. */
  children?: ReactNode;
}

/** The one way to add or edit a personal record: a side sheet with the schema-driven form. */
export function RecordSheet({
  resource,
  record,
  open,
  onClose,
  defaults,
  title,
  note,
  labels,
  hidden,
  recordChoices,
  suggestions,
  onSaved,
  children,
}: RecordSheetProps) {
  const meta = RESOURCES.find(r => r.name === resource);
  const api = RESOURCE_API[resource];
  const fields = useSchemaFields(resource);
  const invalidate = useInvalidateResource();
  const confirm = useConfirm();
  const [historyOpen, setHistoryOpen] = useState(false);

  const save = useMutation({
    retry: false,
    mutationFn: (payload: Record<string, unknown>) => (record ? api.update(record.id, payload) : api.create(payload)),
    onSuccess: saved => {
      notify.success(record ? '저장했습니다' : '추가했습니다');
      onSaved?.(saved);
      onClose();
    },
    onSettled: () => invalidate(resource),
  });
  const remove = useMutation({
    retry: false,
    mutationFn: (id: number) => api.remove(id),
    onSuccess: () => {
      notify.success('삭제했습니다');
      onClose();
    },
    onError: notify.error,
    onSettled: () => invalidate(resource),
  });

  const label = meta?.label ?? '기록';
  const heading = title ?? `${label} ${record ? '수정' : '추가'}`;

  const askRemove = async () => {
    if (!record) return;
    const ok = await confirm({
      title: `${label}을(를) 삭제할까요?`,
      description: meta?.financial
        ? '항목은 목록에서 사라지고, 지금까지의 변경 기록과 월말 기록은 그대로 남습니다.'
        : '이 항목이 목록과 달력에서 사라집니다. 되돌릴 수 없습니다.',
      confirmLabel: '삭제',
      destructive: true,
    });
    if (ok) remove.mutate(record.id);
  };

  return (
    <>
      <Sheet open={open} onOpenChange={next => !next && onClose()}>
        <SheetContent side='right' className='w-[min(480px,100vw)] overflow-y-auto'>
          <div className='flex flex-col gap-3 p-5'>
            <SheetTitle className='pr-8 text-title font-semibold'>{heading}</SheetTitle>
            {note && <p className='text-ui text-muted-foreground'>{note}</p>}
            {children}
            {fields.error && <Alert variant='destructive'>입력 양식을 불러오지 못했습니다.</Alert>}
            {fields.isPending && <ListSkeleton rows={5} />}
            {fields.data && open && (
              <DataForm
                key={record?.id ?? JSON.stringify(defaults ?? {})}
                fields={fields.data}
                labels={labels}
                hidden={hidden}
                recordChoices={recordChoices}
                suggestions={suggestions}
                current={record ?? defaults}
                submitLabel={record ? '저장' : '추가'}
                onSubmit={save.mutateAsync}
                onCancel={onClose}
                extraActions={
                  record && (
                    <>
                      <Button
                        type='button'
                        size='icon'
                        variant='ghost-destructive'
                        aria-label='삭제'
                        disabled={remove.isPending}
                        onClick={() => void askRemove()}>
                        <Trash2 />
                      </Button>
                      {HISTORY_RESOURCES.has(resource) && (
                        <Button type='button' size='icon' variant='ghost' aria-label='변경 기록' onClick={() => setHistoryOpen(true)}>
                          <History />
                        </Button>
                      )}
                    </>
                  )
                }
              />
            )}
          </div>
        </SheetContent>
      </Sheet>
      {historyOpen && record && (
        <ValueHistoryDialog
          resource={resource}
          id={record.id}
          label={String(record.name ?? record.symbol ?? label)}
          onClose={() => setHistoryOpen(false)}
        />
      )}
    </>
  );
}
