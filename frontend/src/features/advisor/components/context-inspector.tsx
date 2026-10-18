'use client';

import { useState } from 'react';

import { X } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';

import { useCompareSnapshot } from '@/api-client/generated/advisor/advisor';
import type { Category } from '@/api-client/model';
import { ALL_CATEGORIES, CATEGORY_LABEL, ROUTE_REASON, TABLE_LABEL, TOOL_LABEL, flagDetail, flagText } from '@/lib/labels';
import { cn } from '@/lib/utils';
import { dateTime, relative } from '@/lib/utils/format';

import { INSPECTOR_TITLE } from '../consts';
import type { InspectorData, InspectorMode } from '../types';
import { groupBy } from '../utils';

interface Props {
  data: InspectorData | null;
  mode: InspectorMode;
  loading?: boolean;
  className?: string;
  onClose?: () => void;
}

function Section({ className, children }: { className?: string; children: React.ReactNode }) {
  return <section className={cn('border-b px-4 py-3.5', className)}>{children}</section>;
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h3 className='mb-2 text-xs text-muted-foreground'>{children}</h3>;
}

/** [참조 중인 데이터] panel (PRD §4.2): which personal data goes (or went) to the model. */
export function ContextInspector({ data, mode, loading, className, onClose }: Props) {
  return (
    <aside className={cn('min-h-0 overflow-y-auto border-l bg-card', className)} aria-label='참조 중인 데이터'>
      <Section className='flex items-center'>
        <h2 className='flex-1 text-[15px]'>참조 중인 데이터</h2>
        {onClose && (
          <Button size='icon' variant='ghost' onClick={onClose} aria-label='닫기'>
            <X />
          </Button>
        )}
      </Section>
      {!data ? (
        <Section className='text-xs text-faint'>
          {loading ? '불러오는 중…' : '질문을 입력하면 어떤 개인 데이터가 AI로 전송되는지 여기에서 먼저 확인할 수 있습니다.'}
        </Section>
      ) : (
        <InspectorBody data={data} mode={mode} />
      )}
    </aside>
  );
}

function InspectorBody({ data, mode }: { data: InspectorData; mode: InspectorMode }) {
  const used = new Set(data.categories);
  const excluded = new Set(data.excluded_categories);
  const refsByTool = groupBy(
    data.record_references.filter(r => r.tool),
    r => r.tool,
  );
  const flags = data.data_quality_flags.filter(f => f.code !== 'category_excluded_by_user');

  return (
    <>
      <Section>
        <SectionTitle>{INSPECTOR_TITLE[mode]}</SectionTitle>
        {data.route && (
          <div className='mb-2 text-xs text-faint'>
            {ROUTE_REASON[data.route.reason]}
            {data.route.matched_terms.length > 0 && ` · ${data.route.matched_terms.slice(0, 4).join(', ')}`}
          </div>
        )}
        {ALL_CATEGORIES.map((c: Category) => {
          const state = used.has(c) ? 'on' : excluded.has(c) ? 'off' : '';
          return (
            <div className='flex items-center gap-2 py-1 text-[13px]' key={c}>
              <span className={cn('size-2 flex-none rounded-full bg-input', state === 'on' && 'bg-primary', state === 'off' && 'bg-destructive')} />
              <span className={cn('flex-1', !state && 'text-faint')}>{CATEGORY_LABEL[c]}</span>
              {state === 'on' && <span className='text-xs text-faint'>{relative(data.source_updated_at[c])}</span>}
              {state === 'off' && <Badge variant='destructive'>공유 제외</Badge>}
              {!state && <span className='text-xs text-faint'>사용 안 함</span>}
            </div>
          );
        })}
      </Section>

      {flags.length > 0 && (
        <Section>
          <SectionTitle>데이터 품질 · 한계</SectionTitle>
          <div className='flex flex-col gap-1.5'>
            {flags.map((f, n) => (
              <div key={n} className='text-xs'>
                <Badge variant='warning'>{f.category === 'documents' ? '문서' : (CATEGORY_LABEL[f.category as Category] ?? f.category)}</Badge>{' '}
                {flagText(f.code)}
                {flagDetail(f.code, f.detail) && <div className='text-faint'>{flagDetail(f.code, f.detail)}</div>}
              </div>
            ))}
          </div>
        </Section>
      )}

      <Section>
        <SectionTitle>문서 근거</SectionTitle>
        {!data.document_citations?.length && <p className='text-xs text-faint'>사용한 문서 발췌문이 없습니다.</p>}
        {data.document_citations?.map(c => (
          <details key={c.ref} className='mb-2 text-xs'>
            <summary className='cursor-pointer'>
              {c.title} · 버전 #{c.version_id}
              {c.page ? ` · p.${c.page}` : ''}
              {c.historical ? ' · 이전 상담 근거' : ''}
            </summary>
            <p className='mt-1 text-faint'>
              {c.filename}
              {c.section ? ` · ${c.section}` : ''}
              {c.as_of ? ` · 기준일 ${c.as_of}` : ''}
            </p>
            <p className='mt-2 whitespace-pre-wrap'>{c.text}</p>
          </details>
        ))}
      </Section>
      <Section>
        <SectionTitle>조회한 레코드</SectionTitle>
        {Object.keys(refsByTool).length === 0 && <div className='text-xs text-faint'>조회된 레코드가 없습니다.</div>}
        {Object.entries(refsByTool).map(([tool, refs]) => (
          <div key={tool} className='mb-2.5'>
            <div className='text-xs font-semibold'>{TOOL_LABEL[tool] ?? tool}</div>
            <div className='mt-1 flex flex-wrap gap-1'>
              {refs.map((r, n) =>
                r.count !== undefined ? (
                  <Badge key={n}>
                    {TABLE_LABEL[r.table ?? ''] ?? r.table} {r.count}건
                  </Badge>
                ) : (
                  <Badge key={n} variant='ref' title={r.updated_at ? `수정 ${dateTime(r.updated_at)}` : undefined}>
                    {TABLE_LABEL[r.table ?? ''] ?? r.table} #{r.id}
                  </Badge>
                ),
              )}
            </div>
          </div>
        ))}
      </Section>

      {mode !== 'preview' && data.context_snapshot_id && <SnapshotSection snapshotId={data.context_snapshot_id} reused={data.context_reused} />}
    </>
  );
}

function SnapshotSection({ snapshotId, reused }: { snapshotId: string; reused: boolean }) {
  const [requested, setRequested] = useState(false);
  const compare = useCompareSnapshot(snapshotId, { query: { enabled: requested, staleTime: 0 } });
  const result = requested ? compare.data : undefined;

  return (
    <Section>
      <SectionTitle>Context Snapshot</SectionTitle>
      <div className='break-all font-mono text-xs text-faint'>{snapshotId}</div>
      {reused && <div className='text-xs text-faint'>직전 질문과 데이터가 같아 기존 스냅샷을 재사용했습니다.</div>}
      <Button size='sm' className='mt-2' disabled={compare.isFetching} onClick={() => (requested ? compare.refetch() : setRequested(true))}>
        현재 데이터와 비교
      </Button>
      {result && (
        <div className='mt-2 text-xs'>
          {result.changed_sections.length === 0 ? (
            <Badge variant='success'>상담 이후 변경 없음</Badge>
          ) : (
            <>
              <div>상담 이후 바뀐 데이터:</div>
              <div className='mt-1 flex flex-wrap gap-1'>
                {result.changed_sections.map(s => (
                  <Badge key={s} variant='warning'>
                    {TOOL_LABEL[s] ?? s}
                  </Badge>
                ))}
              </div>
              <div className='mt-1 text-faint'>답변은 {dateTime(result.snapshot_generated_at)} 기준 데이터로 작성되었습니다.</div>
            </>
          )}
        </div>
      )}
    </Section>
  );
}
