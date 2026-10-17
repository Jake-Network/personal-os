'use client';

import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { financeApi, type Snapshot } from './api';

const KINDS = [
  ['cash', '현금'],
  ['holding', '투자'],
  ['liability', '부채'],
  ['other', '기타'],
] as const;
const FIELDS = [
  ['id', '항목 ID'],
  ['label', '이름'],
  ['currency', '통화'],
  ['as_of', '잔액·수량 기준일'],
  ['balance', '잔액'],
  ['quantity', '수량'],
  ['avg_cost', '평균단가'],
  ['ticker', '종목코드'],
  ['price', '적용 종가·수동 가격'],
  ['price_as_of', '가격 기준일'],
  ['close_valid_through', '마지막 유효 종가 확인일'],
  ['fx_rate', 'KRW 환율'],
  ['fx_as_of', '환율 기준일'],
  ['source', '가격 출처'],
] as const;

export function SnapshotCorrection({ snapshot, onSaved }: { snapshot: Snapshot; onSaved: (snapshot: Snapshot) => void }) {
  const client = useQueryClient();
  const [rows, setRows] = useState(() =>
    (snapshot.rows ?? []).map(row =>
      Object.fromEntries(Object.entries(row).filter(([key]) => FIELDS.some(([field]) => field === key) || key === 'kind' || key === 'asset_class')),
    ),
  );
  const [coverage, setCoverage] = useState(snapshot.coverage ?? []);
  const [reason, setReason] = useState('');
  const correction = useMutation({
    mutationFn: () =>
      financeApi.correct(snapshot.id, {
        reason,
        rows: rows.map(row =>
          Object.fromEntries(
            Object.entries(row).map(([key, value]) => [key, value === '' && !['id', 'label', 'currency', 'as_of'].includes(key) ? null : value]),
          ),
        ),
        coverage,
      }),
    onSuccess: async result => {
      await client.invalidateQueries({ queryKey: ['finance'] });
      onSaved(result);
    },
  });
  function change(index: number, key: string, value: string) {
    setRows(current => current.map((row, rowIndex) => (rowIndex === index ? { ...row, [key]: value } : row)));
  }
  return (
    <details className='rounded-md border p-3'>
      <summary className='cursor-pointer font-semibold'>월말 기록 정정</summary>
      <form
        className='mt-4 space-y-4'
        onSubmit={event => {
          event.preventDefault();
          correction.mutate();
        }}>
        <Alert variant='warning'>
          원본을 보존하고 새 수정본을 추가합니다. 해당 월말의 실제 보유 수량과 잔액을 입력하세요. 마지막 유효 종가 확인일은 그날까지 더 최근 종가가
          없음을 확인한 날짜입니다. 근거 없는 값은 비워 두세요.
        </Alert>
        <div className='flex flex-wrap gap-4'>
          {KINDS.map(([kind, label]) => (
            <label key={kind} className='flex gap-2'>
              <input
                type='checkbox'
                checked={coverage.includes(kind)}
                onChange={event => setCoverage(current => (event.target.checked ? [...current, kind] : current.filter(value => value !== kind)))}
              />
              {label} 전체 항목 확인 (잔액 없음 포함)
            </label>
          ))}
        </div>
        {rows.map((row, index) => (
          <fieldset key={index} className='rounded-md border p-3'>
            <legend>항목 {index + 1}</legend>
            <div className='grid gap-3 sm:grid-cols-3'>
              <label>
                유형
                <select
                  className='block h-8 w-full rounded-md border bg-card'
                  value={row.kind ?? ''}
                  onChange={event => change(index, 'kind', event.target.value)}>
                  {KINDS.map(([kind, label]) => (
                    <option key={kind} value={kind}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                자산군
                <select
                  className='block h-8 w-full rounded-md border bg-card'
                  value={row.asset_class ?? 'other'}
                  onChange={event => change(index, 'asset_class', event.target.value)}>
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
                </select>
              </label>
              {FIELDS.map(([field, label]) => (
                <label key={field} className='text-xs'>
                  {label}
                  <Input
                    type={field.includes('as_of') || field === 'close_valid_through' ? 'date' : 'text'}
                    value={row[field] ?? ''}
                    required={['id', 'label', 'currency', 'as_of'].includes(field)}
                    onChange={event => change(index, field, event.target.value)}
                  />
                </label>
              ))}
            </div>
            <Button
              className='mt-3'
              type='button'
              variant='destructive'
              onClick={() => setRows(current => current.filter((_, rowIndex) => rowIndex !== index))}>
              항목 제외
            </Button>
          </fieldset>
        ))}
        <Button
          type='button'
          onClick={() => setRows(current => [...current, { kind: 'cash', id: '', label: '', currency: 'KRW', as_of: '', asset_class: 'other' }])}>
          항목 추가
        </Button>
        <label className='block'>
          정정 사유
          <Input value={reason} onChange={event => setReason(event.target.value)} minLength={3} maxLength={2000} required />
        </label>
        {correction.error && <Alert variant='destructive'>{correction.error.message}</Alert>}
        <Button variant='primary' disabled={correction.isPending || reason.trim().length < 3} type='submit'>
          새 수정본 저장
        </Button>
      </form>
    </details>
  );
}
