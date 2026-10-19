'use client';

import { useMemo, useState } from 'react';

import { Briefcase, CalendarClock, Plus } from 'lucide-react';

import { TabToolbar } from '@/components/area-layout';
import { EmptyState } from '@/components/empty-state';
import { Section } from '@/components/page-container';
import { QueryStatus } from '@/components/query-status';
import { StatusBadge } from '@/components/status-badge';
import { Button } from '@/components/ui/button';
import { dateTime } from '@/lib/utils/format';
import { cn } from '@/lib/utils';

import type { Row } from '@/features/personal-data/api/resource-api';
import { RecordSheet } from '@/features/personal-data/components/record-sheet';
import { enumLabel } from '@/features/personal-data/consts/resources';
import { useRecordParam } from '@/features/personal-data/hooks/use-record-param';
import { useResourceRows } from '@/features/personal-data/hooks/use-resource';
import { SourceCalendar } from '@/features/plan/source-calendar';
import { useStoredView, ViewToggle } from '@/features/plan/view-toggle';

const OPEN_STAGES = ['interested', 'applied', 'screening', 'interviewing', 'offer'] as const;
const CLOSED_STAGES = new Set(['rejected', 'withdrawn']);

type Sheet = { resource: 'job-applications' | 'interviews'; record: Row | null; defaults?: Record<string, unknown> } | null;

const appLabel = (a: Row) => [a.company, a.role].filter(Boolean).join(' · ');

function upcoming(interviews: Row[], now: number): Row[] {
  return interviews
    .filter(i => typeof i.starts_at === 'string' && new Date(i.starts_at).getTime() >= now)
    .sort((a, b) => String(a.starts_at).localeCompare(String(b.starts_at)));
}

function ApplicationCard({ app, next, onOpen }: { app: Row; next?: Row; onOpen: () => void }) {
  return (
    <button
      type='button'
      onClick={onOpen}
      className='flex w-full flex-col gap-1 rounded-lg border bg-card p-3 text-left shadow-sm hover:border-primary/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring'>
      <span className='font-semibold'>{String(app.company)}</span>
      <span className='text-ui text-muted-foreground'>{String(app.role)}</span>
      {app.next_step ? <span className='text-xs'>다음: {String(app.next_step)}</span> : null}
      {next && (
        <span className='mt-1 inline-flex items-center gap-1 text-xs text-primary'>
          <CalendarClock className='size-3.5' aria-hidden />
          {dateTime(next.starts_at as string)} · {String(next.stage)}
        </span>
      )}
    </button>
  );
}

/** Job applications by stage, with their interviews. */
export function ApplicationsView({ recordId }: { recordId: number | null }) {
  const apps = useResourceRows('job-applications');
  const interviews = useResourceRows('interviews');
  const [view, setView] = useStoredView('career-applications');
  const [selected, setSelected] = useRecordParam(recordId);
  const [sheet, setSheet] = useState<Sheet>(null);
  const [showClosed, setShowClosed] = useState(false);
  // Fixed for the render so upcoming interviews don't shift while the list is open.
  const [now] = useState(() => Date.now());

  const byApp = useMemo(() => {
    const map = new Map<number, Row[]>();
    for (const i of interviews.data ?? []) {
      const id = Number(i.application_id);
      map.set(id, [...(map.get(id) ?? []), i]);
    }
    return map;
  }, [interviews.data]);
  const appChoices = useMemo(() => (apps.data ?? []).map(a => ({ value: String(a.id), label: appLabel(a) })), [apps.data]);
  const appById = useMemo(() => new Map((apps.data ?? []).map(a => [a.id, a])), [apps.data]);

  const deepLinked = selected !== null ? (appById.get(selected) ?? null) : null;
  const active: Sheet = sheet ?? (deepLinked ? { resource: 'job-applications', record: deepLinked } : null);
  const close = () => {
    setSheet(null);
    setSelected(null);
  };
  const openApp = (app: Row) => {
    setSheet(null);
    setSelected(app.id);
  };

  const rows = apps.data ?? [];
  const closed = rows.filter(a => CLOSED_STAGES.has(String(a.status)));
  const nextInterviews = upcoming(interviews.data ?? [], now);
  const openApplication = active?.resource === 'job-applications' ? active.record : null;
  const appInterviews = openApplication ? [...(byApp.get(openApplication.id) ?? [])].sort((a, b) => String(a.starts_at).localeCompare(String(b.starts_at))) : [];

  return (
    <>
      <TabToolbar>
        <Button variant='primary' onClick={() => setSheet({ resource: 'job-applications', record: null, defaults: { status: 'interested' } })}>
          <Plus /> 지원 추가
        </Button>
        <Button onClick={() => setSheet({ resource: 'interviews', record: null })} disabled={!rows.length}>
          <Plus /> 면접 추가
        </Button>
        <div className='ml-auto'>
          <ViewToggle value={view} onChange={setView} />
        </div>
      </TabToolbar>

      <QueryStatus pending={apps.isPending} error={apps.error ?? interviews.error} retry={() => Promise.all([apps.refetch(), interviews.refetch()])} label='채용 지원' />

      {view === 'calendar' ? (
        <SourceCalendar sources={['interviews']} />
      ) : (
        apps.data && (
          <>
            {rows.length === 0 ? (
              <EmptyState
                icon={Briefcase}
                title='진행 중인 지원이 없습니다'
                action={
                  <Button variant='primary' onClick={() => setSheet({ resource: 'job-applications', record: null, defaults: { status: 'interested' } })}>
                    <Plus /> 지원 추가
                  </Button>
                }>
                관심 있는 공고부터 기록하면 단계별로 정리됩니다.
              </EmptyState>
            ) : (
              <div className='mb-7 grid grid-cols-1 gap-4 lg:grid-cols-5'>
                {OPEN_STAGES.map(stage => {
                  const inStage = rows.filter(a => a.status === stage);
                  return (
                    <section key={stage} aria-label={enumLabel(stage)} className='flex min-w-0 flex-col gap-2'>
                      <h2 className='flex items-center gap-1.5 border-b pb-1.5 text-ui font-semibold'>
                        {enumLabel(stage)}
                        <span className='font-normal text-faint'>{inStage.length}</span>
                      </h2>
                      {inStage.map(a => (
                        <ApplicationCard key={a.id} app={a} next={upcoming(byApp.get(a.id) ?? [], now)[0]} onOpen={() => openApp(a)} />
                      ))}
                      {inStage.length === 0 && <p className='py-2 text-xs text-faint'>없음</p>}
                    </section>
                  );
                })}
              </div>
            )}

            {closed.length > 0 && (
              <Section
                title='종료된 지원'
                count={closed.length}
                actions={
                  <Button size='sm' variant='ghost' aria-expanded={showClosed} onClick={() => setShowClosed(v => !v)}>
                    {showClosed ? '접기' : '펼치기'}
                  </Button>
                }>
                {showClosed && (
                  <ul className='divide-y'>
                    {closed.map(a => (
                      <li key={a.id}>
                        <button type='button' onClick={() => openApp(a)} className='flex w-full items-center gap-2 py-2 text-left hover:bg-muted/40'>
                          <span className='flex-1'>{appLabel(a)}</span>
                          <StatusBadge value={String(a.status)} />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </Section>
            )}

            <Section title='다가오는 면접' count={nextInterviews.length}>
              {nextInterviews.length === 0 ? (
                <p className='py-2 text-ui text-muted-foreground'>예정된 면접이 없습니다.</p>
              ) : (
                <ul className='divide-y'>
                  {nextInterviews.map(i => {
                    const app = appById.get(Number(i.application_id));
                    return (
                      <li key={i.id}>
                        <button
                          type='button'
                          onClick={() => setSheet({ resource: 'interviews', record: i })}
                          className='flex w-full flex-wrap items-baseline gap-x-3 gap-y-0.5 py-2 text-left hover:bg-muted/40'>
                          <span className='w-36 shrink-0 text-ui tabular-nums text-muted-foreground'>{dateTime(i.starts_at as string)}</span>
                          <span className='font-medium'>{app ? appLabel(app) : '연결된 지원 없음'}</span>
                          <span className='text-ui text-muted-foreground'>{String(i.stage)}</span>
                          {i.location ? <span className='text-xs text-faint'>{String(i.location)}</span> : null}
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </Section>
          </>
        )
      )}

      {active && (
        <RecordSheet
          key={`${active.resource}:${active.record?.id ?? 'new'}`}
          resource={active.resource}
          record={active.record}
          open
          defaults={active.defaults}
          recordChoices={{ application_id: appChoices }}
          onClose={close}>
          {openApplication && (
            <div className='rounded-lg border p-3'>
              <div className='mb-2 flex items-center gap-2'>
                <h3 className='flex-1 text-ui font-semibold'>면접</h3>
                <Button size='sm' onClick={() => setSheet({ resource: 'interviews', record: null, defaults: { application_id: openApplication.id } })}>
                  <Plus /> 면접 추가
                </Button>
              </div>
              {appInterviews.length === 0 ? (
                <p className='text-xs text-faint'>기록된 면접이 없습니다.</p>
              ) : (
                <ul className='flex flex-col gap-1'>
                  {appInterviews.map(i => (
                    <li key={i.id}>
                      <button
                        type='button'
                        onClick={() => setSheet({ resource: 'interviews', record: i })}
                        className={cn('flex w-full items-baseline gap-2 rounded-md px-1.5 py-1 text-left text-ui hover:bg-muted', new Date(i.starts_at as string).getTime() < now && 'text-muted-foreground')}>
                        <span className='tabular-nums'>{dateTime(i.starts_at as string)}</span>
                        <span>{String(i.stage)}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </RecordSheet>
      )}
    </>
  );
}
