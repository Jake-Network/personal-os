'use client';

import { useState } from 'react';

import { ArrowLeft } from 'lucide-react';
import Link from 'next/link';

import { useCompareSnapshot } from '@/api-client/generated/advisor/advisor';
import type { Category } from '@/api-client/model';
import { ListSkeleton } from '@/components/skeleton';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { ALL_CATEGORIES, CATEGORY_LABEL, TABLE_LABEL, TOOL_LABEL, flagDetail, flagText } from '@/lib/labels';
import { cn } from '@/lib/utils';
import { dateOnly, dateTime, relative } from '@/lib/utils/format';

import { INSPECTOR_TITLE, evidenceHref } from '../consts';
import type { InspectorData, InspectorMode } from '../types';
import { groupBy, publicWebUrl } from '../utils';

interface Props {
  data: InspectorData | null;
  mode: InspectorMode;
  loading?: boolean;
  className?: string;
  /** Leave a saved answer's data and show the current conversation's again. */
  onBack?: () => void;
}

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className='border-b px-4 py-3 last:border-b-0'>
      <h3 className='mb-2 text-xs font-medium text-muted-foreground'>{title}</h3>
      {children}
    </section>
  );
}

/** Which personal data goes (or went) to the model for this conversation. */
export function ContextInspector({ data, mode, loading, className, onBack }: Props) {
  return (
    <div className={cn('min-h-0', className)} aria-label={INSPECTOR_TITLE[mode]}>
      <div className='flex items-center gap-1 border-b px-4 py-2.5'>
        {mode === 'snapshot' && onBack && (
          <Button size='icon-sm' variant='ghost' aria-label='현재 상담 근거로 돌아가기' onClick={onBack}>
            <ArrowLeft />
          </Button>
        )}
        <h3 className='flex-1 text-ui font-semibold'>{INSPECTOR_TITLE[mode]}</h3>
      </div>
      {!data ? (
        loading ? (
          <ListSkeleton rows={3} className='px-4' />
        ) : (
          <p className='px-4 py-3 text-ui text-muted-foreground'>질문을 쓰면 보낼 기록을 먼저 보여드립니다.</p>
        )
      ) : (
        <InspectorBody data={data} mode={mode} />
      )}
    </div>
  );
}

function InspectorBody({ data, mode }: { data: InspectorData; mode: InspectorMode }) {
  const used = ALL_CATEGORIES.filter(c => data.categories.includes(c));
  const excluded = ALL_CATEGORIES.filter(c => data.excluded_categories.includes(c));
  const refsByTool = groupBy(
    // Playbooks have their own block; they are procedures, not personal records.
    data.record_references.filter(r => r.tool && r.tool !== 'playbooks'),
    r => r.tool,
  );
  const flags = data.data_quality_flags.filter(f => f.code !== 'category_excluded_by_user');

  return (
    <>
      <Block title='쓰는 기록'>
        {used.length === 0 && <p className='text-ui text-muted-foreground'>개인 기록을 쓰지 않습니다.</p>}
        {used.map((c: Category) => (
          <div className='flex items-center gap-2 py-0.5 text-ui' key={c}>
            <span className='size-2 flex-none rounded-full bg-primary' aria-hidden />
            <span className='flex-1'>{CATEGORY_LABEL[c]}</span>
            <span className='text-xs text-faint'>{relative(data.source_updated_at[c], '수정 기록 없음')}</span>
          </div>
        ))}
        {excluded.length > 0 && (
          <p className='mt-1.5 text-xs text-faint'>
            공유 제외: {excluded.map(c => CATEGORY_LABEL[c]).join(', ')}
          </p>
        )}
        {!!data.history_withheld_messages && (
          <p className='mt-1.5 text-xs text-faint'>
            공유 제외한 기록이 담겼을 수 있는 이전 메시지 {data.history_withheld_messages}개는 보내지 않습니다.
          </p>
        )}
      </Block>

      {flags.length > 0 && (
        <Block title='확인할 점'>
          <ul className='flex flex-col gap-1.5'>
            {flags.map((f, n) => (
              <li key={n} className='text-xs'>
                <Badge variant='warning'>{f.category === 'documents' ? '문서' : (CATEGORY_LABEL[f.category as Category] ?? '기타')}</Badge> {flagText(f.code)}
                {flagDetail(f.code, f.detail) && <div className='text-faint'>{flagDetail(f.code, f.detail)}</div>}
              </li>
            ))}
          </ul>
        </Block>
      )}

      {!!data.document_citations?.length && (
        <Block title='문서 근거'>
          {data.document_citations.map(c => (
            <details key={c.ref} className='mb-2 text-xs'>
              <summary className='cursor-pointer'>
                {c.title}
                {c.page ? ` · ${c.page}쪽` : ''}
                {c.historical ? ' · 이전 상담 근거' : ''}
              </summary>
              <p className='mt-1 text-faint'>
                {c.filename}
                {c.section ? ` · ${c.section}` : ''}
                {c.as_of ? ` · 기준일 ${dateOnly(c.as_of)}` : ''}
              </p>
              <p className='mt-2 whitespace-pre-wrap'>{c.text}</p>
            </details>
          ))}
        </Block>
      )}

      {!!data.playbooks?.length && (
        <Block title={mode === 'preview' ? '함께 보낼 플레이북' : '따른 플레이북'}>
          <ul className='flex flex-col gap-1 text-xs'>
            {data.playbooks.map(playbook => (
              <li key={playbook.ref}>
                {playbook.playbook_id ? (
                  <Link href={`/reflect/playbooks?record=${playbook.playbook_id}`} className='text-primary hover:underline'>
                    {playbook.title ?? playbook.slug}
                  </Link>
                ) : (
                  (playbook.title ?? playbook.slug)
                )}
                {playbook.slug && <span className='ml-1 text-faint'>/{playbook.slug}</span>}
              </li>
            ))}
          </ul>
          {mode !== 'preview' && <p className='mt-1 text-2xs text-faint'>답변 당시 승인되어 있던 버전입니다. 이후 수정해도 이 답변의 근거는 바뀌지 않습니다.</p>}
        </Block>
      )}

      {!!data.web_sources?.length && (
        <Block title='웹 근거'>
          {data.web_sources.map(source => {
            const url = publicWebUrl(source.url);
            return (
              <details key={source.ref} className='mb-2 text-xs'>
                <summary className='cursor-pointer'>
                  {source.title}
                  {source.historical ? ' · 이전 근거' : ''}
                </summary>
                {url && (
                  <a className='mt-1 block break-all text-primary underline' href={url} target='_blank' rel='noopener noreferrer'>
                    {source.url}
                  </a>
                )}
                <p className='mt-1 text-faint'>
                  {source.published_at ? `발행 ${dateOnly(source.published_at)} · ` : ''}수집 {dateTime(source.retrieved_at)}
                </p>
                {source.excerpts.map((excerpt, index) => (
                  <p key={index} className='mt-2 whitespace-pre-wrap'>
                    {excerpt}
                  </p>
                ))}
              </details>
            );
          })}
        </Block>
      )}

      {Object.keys(refsByTool).length > 0 && (
        <Block title='살펴본 기록'>
          {Object.entries(refsByTool).map(([tool, refs]) => (
            <div key={tool} className='mb-2'>
              <div className='text-xs font-medium'>{TOOL_LABEL[tool] ?? '기타'}</div>
              <div className='mt-1 flex flex-wrap gap-1'>
                {refs.map((r, n) => {
                  const label = TABLE_LABEL[r.table ?? ''] ?? '기록';
                  if (r.count !== undefined) return <Badge key={n}>{`${label} ${r.count}건`}</Badge>;
                  const href = evidenceHref(r.table, r.id);
                  const text = refs.length > 1 ? `${label} ${n + 1}` : label;
                  return href ? (
                    <Link key={n} href={href} className='rounded-sm border bg-muted px-1.5 text-2xs leading-5 text-primary hover:bg-accent' title='기록 열기'>
                      {text}
                    </Link>
                  ) : (
                    <Badge key={n} variant='ref'>
                      {text}
                    </Badge>
                  );
                })}
              </div>
            </div>
          ))}
        </Block>
      )}

      {mode !== 'preview' && data.context_snapshot_id && <SnapshotBlock snapshotId={data.context_snapshot_id} reused={data.context_reused} model={data.model} />}
    </>
  );
}

function SnapshotBlock({ snapshotId, reused, model }: { snapshotId: string; reused: boolean; model?: string | null }) {
  const [requested, setRequested] = useState(false);
  const compare = useCompareSnapshot(snapshotId, { query: { enabled: requested, staleTime: 0 } });
  const result = requested ? compare.data : undefined;

  return (
    <Block title='지금 기록과 비교'>
      <Button size='sm' disabled={compare.isFetching} onClick={() => (requested ? compare.refetch() : setRequested(true))}>
        지금 기록과 비교
      </Button>
      {result && (
        <div className='mt-2 text-xs'>
          {result.changed_sections.length === 0 ? (
            <Badge variant='success'>답변 이후 바뀐 기록 없음</Badge>
          ) : (
            <>
              <div>답변 이후 바뀐 기록</div>
              <div className='mt-1 flex flex-wrap gap-1'>
                {result.changed_sections.map(s => (
                  <Badge key={s} variant='warning'>
                    {TOOL_LABEL[s] ?? '기타'}
                  </Badge>
                ))}
              </div>
              <div className='mt-1 text-faint'>이 답변은 {dateTime(result.snapshot_generated_at)} 기록으로 작성했습니다.</div>
            </>
          )}
        </div>
      )}
      <p className='mt-1.5 text-2xs text-faint'>웹 근거는 다시 조회하지 않습니다.</p>
      <details className='mt-2 text-2xs text-faint'>
        <summary className='cursor-pointer'>자세히</summary>
        {model && <p className='mt-1'>응답 모델 {model}</p>}
        {reused && <p className='mt-1'>직전 질문과 기록이 같아 같은 근거를 다시 썼습니다.</p>}
        <p className='mt-1 break-all font-mono'>{snapshotId}</p>
      </details>
    </Block>
  );
}
