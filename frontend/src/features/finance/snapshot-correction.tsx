'use client';

import { useState } from 'react';

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { Plus, X } from 'lucide-react';

import { InfoPopover } from '@/components/info-popover';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { NativeSelect } from '@/components/ui/native-select';
import { monthLabel } from '@/lib/utils/format';

import { financeApi, type Snapshot } from './api';
import { issueText, POSITION_KIND_LABEL } from './presentation';

const KINDS = ['cash', 'holding', 'liability', 'other'] as const;
type Field = readonly [key: string, label: string, type?: 'date'];

const COMMON: Field[] = [
  ['label', '이름'],
  ['currency', '통화'],
  ['as_of', '잔액·수량 기준일', 'date'],
];
const BALANCE: Field[] = [['balance', '잔액']];
const HOLDING: Field[] = [
  ['ticker', '종목 코드'],
  ['quantity', '수량'],
  ['avg_cost', '평균 매수가'],
  ['price', '적용 종가'],
  ['price_as_of', '종가 날짜', 'date'],
  ['close_valid_through', '종가 확인일', 'date'],
  ['source', '가격 출처'],
];
const FX: Field[] = [
  ['fx_rate', '원화 환율'],
  ['fx_as_of', '환율 기준일', 'date'],
];
const REQUIRED = new Set(['id', 'label', 'currency', 'as_of']);

type EvidenceRow = Record<string, string | null>;

function fieldsFor(row: EvidenceRow): Field[] {
  return [...COMMON, ...(row.kind === 'holding' ? HOLDING : BALANCE), ...(row.currency && row.currency !== 'KRW' ? FX : [])];
}

/** Backend refusals are English; show what the user can act on. */
function correctionError(message: string): string {
  if (message.startsWith('Month already closed')) return '이미 기록된 달입니다. 표에서 그 달을 열어 정정하세요.';
  const incomplete = /^Month-end evidence incomplete: (.*)$/s.exec(message);
  if (incomplete) return ['월말 근거가 부족해 확정하지 않았습니다.', ...incomplete[1].split('; ').map(issueText)].join('\n');
  return message;
}

export type CorrectionTarget = { kind: 'create'; month: string } | { kind: 'correct'; snapshot: Snapshot };

/** Month-end evidence as of that month: create a month or append a correction; the original is never overwritten. */
export function SnapshotCorrection({ target, onSaved, onCancel }: { target: CorrectionTarget; onSaved: (snapshot: Snapshot) => void; onCancel: () => void }) {
  const client = useQueryClient();
  const source = target.kind === 'correct' ? target.snapshot : null;
  const [rows, setRows] = useState<EvidenceRow[]>(() =>
    (source?.rows ?? []).map(row =>
      Object.fromEntries(Object.entries(row).filter(([key]) => [...COMMON, ...BALANCE, ...HOLDING, ...FX].some(([f]) => f === key) || ['id', 'kind', 'asset_class'].includes(key))),
    ),
  );
  const [coverage, setCoverage] = useState<string[]>(source?.coverage ?? []);
  const [reason, setReason] = useState('');
  const correction = useMutation({
    mutationFn: () => {
      const body = {
        reason,
        rows: rows.map(row => Object.fromEntries(Object.entries(row).map(([key, value]) => [key, value === '' && !REQUIRED.has(key) ? null : value]))),
        coverage,
      };
      return target.kind === 'create' ? financeApi.closeMonth({ month: `${target.month}-01`, ...body }) : financeApi.correct(target.snapshot.id, body);
    },
    onSuccess: async result => {
      await client.invalidateQueries({ queryKey: ['finance'] });
      onSaved(result);
    },
  });
  const change = (index: number, key: string, value: string) => setRows(current => current.map((row, i) => (i === index ? { ...row, [key]: value } : row)));

  return (
    <form
      className='flex flex-col gap-4'
      onSubmit={event => {
        event.preventDefault();
        correction.mutate();
      }}>
      <p className='flex items-start gap-1 text-ui text-muted-foreground'>
        <span className='flex-1'>그 달 말일 기준의 실제 잔액·수량과 종가를 입력하세요. 근거가 없는 값은 비워 두세요.</span>
        <InfoPopover>
          <p>{target.kind === 'create' ? '근거가 모두 갖춰져야 그 달을 확정합니다.' : '기존 기록은 그대로 두고 정정본을 새로 추가합니다.'}</p>
          <p>종가 확인일은 그날까지 더 최근 종가가 없음을 확인한 날짜입니다. 오늘의 수량이나 시세로 과거를 채우지 마세요.</p>
        </InfoPopover>
      </p>

      <fieldset className='flex flex-col gap-2'>
        <legend className='mb-1 text-ui font-medium'>빠짐없이 입력한 분류</legend>
        <div className='flex flex-wrap gap-x-4 gap-y-2'>
          {KINDS.map(kind => (
            <label key={kind} className='inline-flex items-center gap-2 text-ui'>
              <Checkbox checked={coverage.includes(kind)} onCheckedChange={v => setCoverage(current => (v === true ? [...current, kind] : current.filter(k => k !== kind)))} />
              {POSITION_KIND_LABEL[kind]}
            </label>
          ))}
        </div>
        <p className='text-xs text-faint'>체크한 분류에 없는 항목은 그 달에 없었던 것으로 봅니다.</p>
      </fieldset>

      {rows.map((row, index) => (
        <fieldset key={row.id ?? index} className='rounded-lg border p-3'>
          <div className='mb-2 flex items-center gap-2'>
            <legend className='flex-1 text-ui font-medium'>{row.label || `항목 ${index + 1}`}</legend>
            <Button type='button' size='icon-sm' variant='ghost-destructive' aria-label='이 항목 빼기' onClick={() => setRows(current => current.filter((_, i) => i !== index))}>
              <X />
            </Button>
          </div>
          <div className='grid grid-cols-2 gap-3'>
            <div className='flex flex-col gap-1'>
              <Label htmlFor={`k-${index}`}>분류</Label>
              <NativeSelect id={`k-${index}`} value={row.kind ?? 'cash'} onChange={e => change(index, 'kind', e.target.value)}>
                {KINDS.map(kind => (
                  <option key={kind} value={kind}>
                    {POSITION_KIND_LABEL[kind]}
                  </option>
                ))}
              </NativeSelect>
            </div>
            {row.kind === 'holding' && (
              <div className='flex flex-col gap-1'>
                <Label htmlFor={`c-${index}`}>자산군</Label>
                <NativeSelect id={`c-${index}`} value={row.asset_class ?? 'other'} onChange={e => change(index, 'asset_class', e.target.value)}>
                  {[
                    ['equity', '주식'],
                    ['etf', 'ETF'],
                    ['bond', '채권'],
                    ['crypto', '가상자산'],
                    ['other', '기타'],
                  ].map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </NativeSelect>
              </div>
            )}
            {fieldsFor(row).map(([field, label, type]) => (
              <div key={field} className='flex flex-col gap-1'>
                <Label htmlFor={`${field}-${index}`}>
                  {label}
                  {REQUIRED.has(field) && <span className='text-destructive'> *</span>}
                </Label>
                <Input
                  id={`${field}-${index}`}
                  type={type ?? 'text'}
                  value={row[field] ?? ''}
                  required={REQUIRED.has(field)}
                  onChange={event => change(index, field, field === 'currency' ? event.target.value.toUpperCase() : event.target.value)}
                />
              </div>
            ))}
          </div>
        </fieldset>
      ))}
      <div>
        <Button
          type='button'
          size='sm'
          onClick={() =>
            // The row identity only has to be unique within this month's record.
            setRows(current => [...current, { kind: 'cash', id: `entry-${crypto.randomUUID().slice(0, 8)}`, label: '', currency: 'KRW', as_of: '', asset_class: 'other' }])
          }>
          <Plus /> 항목 추가
        </Button>
      </div>
      <div className='flex flex-col gap-1'>
        <Label htmlFor='correction-reason'>{target.kind === 'create' ? '기록 메모' : '정정 사유'} *</Label>
        <Input id='correction-reason' value={reason} onChange={event => setReason(event.target.value)} minLength={3} maxLength={2000} required />
      </div>
      {correction.error && (
        <Alert variant='destructive' className='whitespace-pre-wrap'>
          {correctionError(correction.error.message)}
        </Alert>
      )}
      <div className='flex justify-end gap-2'>
        <Button type='button' onClick={onCancel}>
          취소
        </Button>
        <Button variant='primary' disabled={correction.isPending || reason.trim().length < 3} type='submit'>
          {target.kind === 'create' ? `${monthLabel(target.month)} 기록` : '정정본 저장'}
        </Button>
      </div>
    </form>
  );
}
