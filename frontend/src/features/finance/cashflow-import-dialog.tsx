'use client';

import { useMemo, useRef, useState } from 'react';

import { useQueryClient } from '@tanstack/react-query';
import { Upload } from 'lucide-react';

import {
  getCashflowCategoryRulesQueryKey,
  getCashflowImportPresetsQueryKey,
  useCashflowImportCommit,
  useCashflowImportPresets,
  useCashflowImportPreview,
  useSaveCashflowImportPresets,
} from '@/api-client/generated/portfolio/portfolio';
import type { CashflowColumnMapping, CashflowImportInput, CashflowImportPreview, CashflowImportPreset } from '@/api-client/model';
import { notify } from '@/components/notify';
import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect } from '@/components/ui/native-select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { dateOnly } from '@/lib/utils/format';

import { cashflowCategories } from './cashflow-categories';
import { decodeCsvBytes, guessMapping, headerColumns, sourceIdFrom } from './cashflow-import';
import { money } from './presentation';

type AmountShape = 'single' | 'split';
type Format = Pick<CashflowImportPreset, 'amount_sign' | 'skip_rows'> & { mapping: Partial<CashflowColumnMapping> };

const FIELD_LABEL: Record<keyof CashflowColumnMapping, string> = {
  date: '날짜',
  amount: '금액',
  debit: '출금(지출)',
  credit: '입금(수입)',
  description: '적요·가맹점',
  category: '분류 (선택)',
};
const STATUS_LABEL = { new: '새 기록', existing: '이미 가져옴', deleted: '삭제한 기록', excluded: '제외' } as const;

/** Imports a bank or card CSV into the household ledger after a server preview. */
export function CashflowImportDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const client = useQueryClient();
  const presets = useCashflowImportPresets({ query: { enabled: open } });
  const savePresets = useSaveCashflowImportPresets();
  const preview = useCashflowImportPreview();
  const commit = useCashflowImportCommit();
  const [text, setText] = useState('');
  const [sourceId, setSourceId] = useState('');
  const [shape, setShape] = useState<AmountShape>('single');
  const [format, setFormat] = useState<Format>({ mapping: {}, amount_sign: 'negative_is_expense', skip_rows: 0 });
  const [excluded, setExcluded] = useState<Set<number>>(new Set());
  const [overrides, setOverrides] = useState<Record<number, string>>({});
  const [remember, setRemember] = useState<Set<number>>(new Set());
  const [presetName, setPresetName] = useState('');
  const savedPresets = presets.data?.presets ?? [];
  const columns = useMemo(() => headerColumns(text, format.skip_rows ?? 0), [text, format.skip_rows]);
  const [data, setData] = useState<CashflowImportPreview>();
  const previewGeneration = useRef(0);

  const invalidatePreview = () => {
    previewGeneration.current += 1;
    setData(undefined);
    setExcluded(new Set());
    setOverrides({});
    setRemember(new Set());
    preview.reset();
  };
  const reset = () => {
    invalidatePreview();
    setText('');
    setSourceId('');
  };
  const updateFormat = (update: (current: Format) => Format) => {
    invalidatePreview();
    setFormat(update);
  };
  const fields: (keyof CashflowColumnMapping)[] = shape === 'single' ? ['date', 'amount', 'description', 'category'] : ['date', 'debit', 'credit', 'description', 'category'];
  const mapping: CashflowColumnMapping = { date: format.mapping.date ?? '' };
  for (const field of fields) if (field !== 'date' && format.mapping[field]) mapping[field] = format.mapping[field];
  const mappingReady = Boolean(mapping.date && (shape === 'single' ? mapping.amount : mapping.debit || mapping.credit));
  const body = (): CashflowImportInput => ({
    source_id: sourceId,
    csv_text: text,
    mapping,
    amount_sign: format.amount_sign,
    skip_rows: format.skip_rows,
    exclude_rows: [...excluded],
    category_overrides: Object.fromEntries(Object.entries(overrides)),
    remember_rows: [...remember].filter(row => overrides[row]),
  });

  const loadFile = async (file: File) => {
    reset();
    const decoded = decodeCsvBytes(await file.arrayBuffer());
    setText(decoded);
    setSourceId(sourceIdFrom(file.name));
    const guessed = guessMapping(headerColumns(decoded, format.skip_rows ?? 0));
    setShape(guessed.debit || guessed.credit ? 'split' : 'single');
    setFormat(current => ({ ...current, mapping: { ...guessed } }));
  };
  const applyPreset = (name: string) => {
    const preset = savedPresets.find(p => p.name === name);
    if (!preset) return;
    invalidatePreview();
    setShape(preset.mapping.debit || preset.mapping.credit ? 'split' : 'single');
    setFormat({ mapping: preset.mapping, amount_sign: preset.amount_sign, skip_rows: preset.skip_rows });
    setPresetName(preset.name);
  };
  const runPreview = async () => {
    const generation = ++previewGeneration.current;
    setData(undefined);
    const result: CashflowImportPreview = await preview.mutateAsync({ data: { ...body(), exclude_rows: [] } });
    // Editing the import format or closing the dialog invalidates even an in-flight response.
    if (generation !== previewGeneration.current) return;
    setData(result);
    // Rows that look like an entry already typed by hand start excluded; the user can include them.
    setExcluded(new Set(result.rows.filter(r => r.possible_duplicate).map(r => r.row)));
  };
  const savePreset = async () => {
    const name = presetName.trim();
    if (!name || !mappingReady) return;
    const others = savedPresets.filter(p => p.name !== name);
    await savePresets.mutateAsync(
      { data: { presets: [...others, { name, mapping, amount_sign: format.amount_sign, skip_rows: format.skip_rows }] } },
      { onError: notify.error },
    );
    notify.success(`'${name}' 형식을 저장했습니다`);
    await client.invalidateQueries({ queryKey: getCashflowImportPresetsQueryKey() });
  };
  const runImport = () => {
    if (!data || preview.isPending || commit.isPending) return;
    commit.mutate(
      { data: body() },
      {
        onSuccess: async result => {
          notify.success(
            `${result.imported}건을 장부에 추가했습니다${result.existing ? ` · 이미 있던 ${result.existing}건 건너뜀` : ''}${result.rules_created ? ` · 분류 규칙 ${result.rules_created}개 저장` : ''}`,
          );
          await Promise.all([
            client.invalidateQueries({ queryKey: ['finance'] }),
            client.invalidateQueries({ queryKey: ['/api/finance/cashflow'] }),
            client.invalidateQueries({ queryKey: ['/api/dashboard/summary'] }),
            client.invalidateQueries({ queryKey: getCashflowCategoryRulesQueryKey() }),
          ]);
          reset();
          onOpenChange(false);
        },
        onError: notify.error,
      },
    );
  };

  const included = data?.rows.filter(r => !excluded.has(r.row)) ?? [];
  const blocking = included.filter(r => r.issues.length > 0).length;
  const toAdd = included.filter(r => r.status === 'new').length;
  const toggle = (set: Set<number>, row: number) => {
    const next = new Set(set);
    if (next.has(row)) next.delete(row);
    else next.add(row);
    return next;
  };

  return (
    <Dialog
      open={open}
      onOpenChange={next => {
        if (!next) reset();
        onOpenChange(next);
      }}>
      <DialogContent className='w-[min(960px,calc(100%-32px))]'>
        <DialogHeader>
          <DialogTitle>은행·카드 내역 가져오기</DialogTitle>
          <DialogDescription>
            CSV 파일의 열을 장부 항목에 맞추고 미리 본 뒤 가져옵니다. 파일은 이 기기의 서버로만 보내고 브라우저에 저장하지 않습니다. 새 기록은 원화로 저장합니다.
          </DialogDescription>
        </DialogHeader>

        <div className='grid gap-3 sm:grid-cols-2'>
          <div>
            <Label htmlFor='cashflow-csv-file'>CSV 파일</Label>
            <Input id='cashflow-csv-file' type='file' accept='.csv,.tsv,.txt,text/csv' onChange={e => e.target.files?.[0] && void loadFile(e.target.files[0])} />
          </div>
          <div>
            <Label htmlFor='cashflow-csv-preset'>저장한 형식</Label>
            <NativeSelect id='cashflow-csv-preset' value='' onChange={e => applyPreset(e.target.value)} disabled={!savedPresets.length}>
              <option value=''>{savedPresets.length ? '형식 불러오기' : '저장한 형식 없음'}</option>
              {savedPresets.map(p => (
                <option key={p.name} value={p.name}>
                  {p.name}
                </option>
              ))}
            </NativeSelect>
          </div>
        </div>

        {text && (
          <div className='mt-4 flex flex-col gap-3'>
            <div className='grid gap-3 sm:grid-cols-3'>
              <div>
                <Label htmlFor='cashflow-csv-source'>원본 이름 (같은 계좌·카드는 같게)</Label>
                <Input
                  id='cashflow-csv-source'
                  value={sourceId}
                  pattern='[A-Za-z0-9_-]+'
                  onChange={e => {
                    invalidatePreview();
                    setSourceId(e.target.value);
                  }}
                />
              </div>
              <div>
                <Label htmlFor='cashflow-csv-skip'>머리글 앞 줄 수</Label>
                <Input
                  id='cashflow-csv-skip'
                  type='number'
                  min={0}
                  max={50}
                  value={format.skip_rows ?? 0}
                  onChange={e => updateFormat(f => ({ ...f, skip_rows: Math.max(0, Math.min(50, Number(e.target.value) || 0)) }))}
                />
              </div>
              <div>
                <Label htmlFor='cashflow-csv-shape'>금액 열</Label>
                <NativeSelect
                  id='cashflow-csv-shape'
                  value={shape}
                  onChange={e => {
                    invalidatePreview();
                    setShape(e.target.value as AmountShape);
                  }}>
                  <option value='single'>금액 열 하나</option>
                  <option value='split'>출금·입금 열 따로</option>
                </NativeSelect>
              </div>
            </div>
            {columns.length === 0 && <Alert variant='destructive'>머리글 행을 찾지 못했습니다. 머리글 앞 줄 수를 확인하세요.</Alert>}
            <div className='grid gap-3 sm:grid-cols-3'>
              {fields.map(field => (
                <div key={field}>
                  <Label htmlFor={`cashflow-csv-${field}`}>{FIELD_LABEL[field]}</Label>
                  <NativeSelect
                    id={`cashflow-csv-${field}`}
                    value={format.mapping[field] ?? ''}
                    onChange={e => updateFormat(f => ({ ...f, mapping: { ...f.mapping, [field]: e.target.value || undefined } }))}>
                    <option value=''>선택 안 함</option>
                    {columns.map(c => (
                      <option key={c} value={c}>
                        {c}
                      </option>
                    ))}
                  </NativeSelect>
                </div>
              ))}
              {shape === 'single' && (
                <div>
                  <Label htmlFor='cashflow-csv-sign'>지출 표시</Label>
                  <NativeSelect
                    id='cashflow-csv-sign'
                    value={format.amount_sign}
                    onChange={e => updateFormat(f => ({ ...f, amount_sign: e.target.value as Format['amount_sign'] }))}>
                    <option value='negative_is_expense'>음수가 지출 (통장 내역)</option>
                    <option value='positive_is_expense'>양수가 지출 (카드 이용 내역)</option>
                  </NativeSelect>
                </div>
              )}
            </div>
            <div className='flex flex-wrap items-end gap-2'>
              <Button variant='primary' disabled={!mappingReady || !sourceId || preview.isPending} onClick={() => void runPreview().catch(notify.error)}>
                미리보기
              </Button>
              <Input aria-label='형식 이름' placeholder='형식 이름 (예: 카드 이용내역)' value={presetName} onChange={e => setPresetName(e.target.value)} className='w-60' />
              <Button disabled={!presetName.trim() || !mappingReady || savePresets.isPending} onClick={() => void savePreset()}>
                이 형식 저장
              </Button>
            </div>
          </div>
        )}

        {data && (
          <div className='mt-4 flex flex-col gap-3'>
            <p className='text-ui'>
              가져올 새 기록 <strong>{toAdd}건</strong>
              {data.counts.existing ? ` · 이미 가져온 ${data.counts.existing}건` : ''}
              {data.counts.deleted ? ` · 삭제한 기록 ${data.counts.deleted}건은 다시 만들지 않음` : ''}
              {blocking ? <span className='text-destructive'> · 문제 있는 행 {blocking}건</span> : ''}
            </p>
            {data.coverage.partial_months.length > 0 && (
              <Alert>
                {data.coverage.partial_months.join(', ')}은(는) 파일에 일부 기간만 들어 있습니다 ({dateOnly(data.coverage.first_date)}~{dateOnly(data.coverage.last_date)}). 그 달
                지출 합계는 완전한 한 달이 아니므로, 나머지 내역을 가져온 뒤 월평균을 판단하세요.
              </Alert>
            )}
            {data.rows.some(r => r.possible_duplicate) ? (
              <p className='text-xs text-muted-foreground'>같은 날짜·금액의 기록이 이미 있는 행은 직접 입력한 기록일 수 있어 제외해 두었습니다. 다른 거래라면 포함하세요.</p>
            ) : null}
            <div className='max-h-[40vh] overflow-auto rounded-md border'>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className='w-10'>포함</TableHead>
                    <TableHead>날짜</TableHead>
                    <TableHead>적요</TableHead>
                    <TableHead className='text-right'>금액</TableHead>
                    <TableHead>분류</TableHead>
                    <TableHead>상태</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.rows.map(r => {
                    const off = excluded.has(r.row);
                    const category = overrides[r.row] ?? r.category ?? '';
                    return (
                      <TableRow key={r.row} className={off ? 'opacity-50' : undefined}>
                        <TableCell>
                          <Checkbox aria-label={`${r.row}행 포함`} checked={!off} onCheckedChange={() => setExcluded(s => toggle(s, r.row))} />
                        </TableCell>
                        <TableCell className='whitespace-nowrap text-xs'>{r.occurred_on ? dateOnly(r.occurred_on) : '—'}</TableCell>
                        <TableCell className='max-w-56 truncate text-xs'>{r.description ?? '—'}</TableCell>
                        <TableCell className={`whitespace-nowrap text-right tabular-nums ${r.kind === 'income' ? 'text-success' : ''}`}>
                          {r.amount ? `${r.kind === 'income' ? '+' : '-'}${money(r.amount, r.currency)}` : '—'}
                        </TableCell>
                        <TableCell>
                          <div className='flex items-center gap-1'>
                            <Input
                              aria-label={`${r.row}행 분류`}
                              list={`cashflow-import-categories-${r.kind ?? ''}`}
                              value={category}
                              placeholder='미분류'
                              className='h-7 w-28 text-xs'
                              onChange={e => setOverrides(o => ({ ...o, [r.row]: e.target.value }))}
                            />
                            {overrides[r.row] && r.description && (
                              <label className='flex items-center gap-1 text-2xs text-muted-foreground'>
                                <Checkbox checked={remember.has(r.row)} onCheckedChange={() => setRemember(s => toggle(s, r.row))} />
                                규칙
                              </label>
                            )}
                            {!overrides[r.row] && r.category_source === 'rule' && <span className='text-2xs text-faint'>규칙</span>}
                          </div>
                        </TableCell>
                        <TableCell className='text-xs'>
                          {r.issues.length ? (
                            <span className='text-destructive'>{r.issues.join(', ')}</span>
                          ) : (
                            <Badge variant={!off && r.status === 'new' ? 'success' : 'default'}>{off ? STATUS_LABEL.excluded : STATUS_LABEL[r.status]}</Badge>
                          )}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
            {(['income', 'expense', ''] as const).map(kind => (
              <datalist key={kind} id={`cashflow-import-categories-${kind}`}>
                {cashflowCategories(kind).map(value => (
                  <option key={value} value={value} />
                ))}
              </datalist>
            ))}
            <div className='flex justify-end gap-2'>
              <Button variant='primary' disabled={blocking > 0 || toAdd === 0 || commit.isPending} onClick={runImport}>
                <Upload /> {toAdd}건 가져오기
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
