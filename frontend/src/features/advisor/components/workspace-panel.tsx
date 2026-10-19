'use client';

import { useRef, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { errorMessage } from '@/api-client/api-error';
import { useListProposals } from '@/api-client/generated/proposals/proposals';
import { getListDecisionsQueryKey, useCreateDecision } from '@/api-client/generated/memory/memory';
import type { ScenarioView } from '@/api-client/model';
import { Alert } from '@/components/ui/alert';
import { X } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Textarea } from '@/components/ui/textarea';
import { Input } from '@/components/ui/input';
import { advisorLabel, advisorValue, visibleAdvisorEntries } from '../presentation';
import { cn } from '@/lib/utils';
import { dateTime } from '@/lib/utils/format';
import { workspaceApi, workspaceKey } from '../api';
import { useWorkspace, isUnfinished } from '../hooks/use-workspace';
import type { InspectorData, InspectorMode } from '../types';
import { ContextInspector } from './context-inspector';
import { ProposalCard } from './proposal-card';

function Values({ value }: { value: Record<string, unknown> }) {
  return (
    <dl className='grid gap-1 text-xs'>
      {visibleAdvisorEntries(value).map(([key, item]) => (
        <div key={key}>
          <dt className='text-muted-foreground'>{advisorLabel(key)}</dt>
          <dd className='whitespace-pre-wrap break-words'>{advisorValue(item, key)}</dd>
        </div>
      ))}
    </dl>
  );
}

function ScenarioCard({
  scenario,
  selected,
  busy,
  onSelect,
  onRevise,
  onDecision,
}: {
  scenario: ScenarioView;
  selected: boolean;
  busy: boolean;
  onSelect: () => void;
  onRevise: (condition: string) => Promise<unknown>;
  onDecision: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [condition, setCondition] = useState('');
  return (
    <article className='grid gap-2 rounded-lg border p-3'>
      <div className='flex flex-wrap items-center gap-1'>
        <h3 className='text-sm font-medium'>{scenario.title}</h3>
        {selected && <Badge variant='accent'>이 대안으로 이어가는 중</Badge>}
      </div>
      <p className='text-xs text-faint'>{dateTime(scenario.created_at)} 분석</p>
      {!!Object.keys(scenario.assumptions).length && (
        <>
          <p className='text-xs font-medium'>가정</p>
          <Values value={scenario.assumptions} />
        </>
      )}
      {!!Object.keys(scenario.constraints).length && (
        <>
          <p className='text-xs font-medium'>제약</p>
          <Values value={scenario.constraints} />
        </>
      )}
      {!!Object.keys(scenario.results).length && (
        <>
          <p className='text-xs font-medium'>계산 결과</p>
          <Values value={scenario.results} />
        </>
      )}
      {!!scenario.unknowns.length && <p className='text-xs text-warning'>확인 필요: {scenario.unknowns.map(String).join(', ')}</p>}
      {!!Object.keys(scenario.evidence).length && (
        <details className='text-xs'>
          <summary className='cursor-pointer'>분석 당시 근거</summary>
          <Values value={scenario.evidence} />
        </details>
      )}
      <div className='flex flex-wrap gap-1.5'>
        <Button size='sm' variant='primary' disabled={busy} onClick={onDecision}>
          이걸로 결정
        </Button>
        <Button size='sm' disabled={busy || selected} onClick={onSelect}>
          이 대안으로 이어가기
        </Button>
        <Button size='sm' variant='ghost' aria-expanded={editing} disabled={busy} onClick={() => setEditing(!editing)}>
          조건 바꿔 보기
        </Button>
      </div>
      {editing && (
        <div className='grid gap-2'>
          <Textarea
            aria-label={`${scenario.title} 변경할 조건`}
            placeholder='예: 퇴사 시점을 3개월 늦추면?'
            value={condition}
            onChange={e => setCondition(e.target.value)}
          />
          <Button
            size='sm'
            disabled={busy || !condition.trim()}
            onClick={() =>
              void onRevise(condition.trim()).then(() => {
                setEditing(false);
                setCondition('');
              })
            }>
            바꾼 조건으로 다시 분석
          </Button>
        </div>
      )}
    </article>
  );
}

export function WorkspacePanel({
  conversationId,
  inspector,
  className,
  onClose,
  onBack,
}: {
  conversationId: number | null;
  inspector: { data: InspectorData | null; mode: InspectorMode; loading?: boolean };
  className?: string;
  onClose?: () => void;
  /** Return from a saved answer's data to the current conversation's. */
  onBack?: () => void;
}) {
  const workspace = useWorkspace(conversationId, false);
  const queryClient = useQueryClient();
  const evidenceKey = inspector.mode === 'snapshot' ? (inspector.data?.context_snapshot_id ?? 'loading') : 'preview';
  const [tabState, setTabState] = useState({ value: 'evidence', evidenceKey });
  if (tabState.evidenceKey !== evidenceKey) setTabState({ value: inspector.mode === 'snapshot' ? 'evidence' : tabState.value, evidenceKey });
  const tab = tabState.evidenceKey !== evidenceKey && inspector.mode === 'snapshot' ? 'evidence' : tabState.value;
  const proposals = useListProposals(
    { status: 'pending' },
    { query: { enabled: conversationId !== null, select: list => list.filter(p => p.conversation_id === conversationId) } },
  );
  const [decision, setDecision] = useState<{ scenario: ScenarioView; rationale: string; expected: string; reviewOn: string } | null>(null);
  const recordDecision = useCreateDecision({
    mutation: {
      onSuccess: () => {
        setDecision(null);
        return queryClient.invalidateQueries({ queryKey: getListDecisionsQueryKey() });
      },
    },
  });
  const scenarioRequests = useRef(new Map<string, { scenarioRequest: string; runRequest: string }>());
  const mutation = useMutation({
    mutationFn: async ({ scenario, condition }: { scenario: ScenarioView; condition?: string }) => {
      if (condition) {
        const key = `${scenario.id}:${scenario.revision}:${condition}`;
        const requests = scenarioRequests.current.get(key) ?? { scenarioRequest: crypto.randomUUID(), runRequest: crypto.randomUUID() };
        scenarioRequests.current.set(key, requests);
        const version = await workspaceApi.createScenario(conversationId!, {
          request_id: requests.scenarioRequest,
          title: scenario.title,
          parent_id: scenario.id,
          parent_revision: scenario.revision,
          assumptions: { ...scenario.assumptions, requested_change: condition },
          constraints: scenario.constraints,
        });
        await workspaceApi.createRun(conversationId!, {
          request_id: requests.runRequest,
          message: `${scenario.title}: ${condition}\n변경한 조건으로 대안을 다시 비교해 주세요.`,
          scenario_id: version.id,
          parent_revision: workspace.data?.revision,
          depth: 'auto',
        });
        scenarioRequests.current.delete(key);
      } else await workspaceApi.selectScenario(conversationId!, { scenario_id: scenario.id, expected_revision: workspace.data?.revision ?? 1 });
      await queryClient.invalidateQueries({ queryKey: workspaceKey(conversationId) });
    },
  });
  const clearSelection = useMutation({
    mutationFn: () => workspaceApi.selectScenario(conversationId!, { scenario_id: null, expected_revision: workspace.data?.revision ?? 1 }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: workspaceKey(conversationId) }),
  });
  const run = workspace.run;
  const busy = mutation.isPending || clearSelection.isPending || isUnfinished(workspace.data?.active_run?.status);
  const currentIds = (run?.result?.scenarios ?? []) as string[];
  const currentScenarios = (workspace.data?.scenarios ?? []).filter(scenario => currentIds.includes(scenario.id)).slice(0, 3);
  const historicalScenarios = (workspace.data?.scenarios ?? []).filter(scenario => !currentIds.includes(scenario.id));
  const renderScenario = (scenario: ScenarioView) => (
    <ScenarioCard
      key={scenario.id}
      scenario={scenario}
      selected={scenario.id === workspace.data?.selected_scenario_id}
      busy={busy}
      onSelect={() => mutation.mutate({ scenario })}
      onRevise={condition => mutation.mutateAsync({ scenario, condition })}
      onDecision={() => setDecision({ scenario, rationale: '', expected: '', reviewOn: '' })}
    />
  );
  const hasScenarios = !!workspace.data?.scenarios?.length;
  const pendingCount = proposals.data?.length ?? 0;
  const activeTab = tab === 'consultation' && !hasScenarios && !decision ? 'evidence' : tab;
  return (
    <aside className={cn('min-h-0 overflow-y-auto border-l bg-card', className)} aria-label='상담 근거와 제안'>
      <Tabs value={activeTab} onValueChange={value => setTabState({ value, evidenceKey })}>
        <div className='sticky top-0 z-10 flex items-center gap-1 border-b bg-card px-3 py-2'>
          <TabsList className='flex-1'>
            <TabsTrigger value='evidence' className='flex-1'>
              근거
            </TabsTrigger>
            {hasScenarios && (
              <TabsTrigger value='consultation' className='flex-1'>
                비교
              </TabsTrigger>
            )}
            <TabsTrigger value='actions' className='flex-1'>
              제안{pendingCount > 0 ? ` ${pendingCount}` : ''}
            </TabsTrigger>
          </TabsList>
          {onClose && (
            <Button size='icon-sm' variant='ghost' aria-label='닫기' onClick={onClose}>
              <X />
            </Button>
          )}
        </div>
        <TabsContent value='consultation' className='mt-0 grid gap-3 p-3'>
          {workspace.error && <Alert variant='destructive'>{errorMessage(workspace.error)}</Alert>}
          {mutation.error && <Alert variant='destructive'>{errorMessage(mutation.error)}</Alert>}
          {clearSelection.error && <Alert variant='destructive'>{errorMessage(clearSelection.error)}</Alert>}
          {workspace.data?.selected_scenario_id && (
            <Button size='sm' variant='ghost' className='justify-self-start' disabled={busy} onClick={() => clearSelection.mutate()}>
              대안 선택 해제하고 새 주제로
            </Button>
          )}
          {!!Object.keys(workspace.data?.problem ?? {}).length && <Values value={workspace.data?.problem ?? {}} />}
          {currentScenarios.length > 0 && (
            <>
              <h3 className='text-sm font-medium'>이번 비교</h3>
              {currentScenarios.map(renderScenario)}
            </>
          )}
          {historicalScenarios.length > 0 && (
            <details className='grid gap-3'>
              <summary className='mb-2 cursor-pointer text-sm'>이전에 비교한 대안 {historicalScenarios.length}개</summary>
              <div className='grid gap-3'>{historicalScenarios.map(renderScenario)}</div>
            </details>
          )}
          {decision && (
            <form
              className='grid gap-2 rounded-lg border p-3'
              onSubmit={event => {
                event.preventDefault();
                recordDecision.mutate({
                  data: {
                    title: decision.scenario.title,
                    choice: decision.scenario.title,
                    rationale: decision.rationale,
                    alternatives: currentScenarios.filter(scenario => scenario.id !== decision.scenario.id).map(scenario => scenario.title),
                    expected_outcome: decision.expected || null,
                    review_on: decision.reviewOn || null,
                    conversation_id: conversationId,
                    context_snapshot_id:
                      (decision.scenario.evidence.snapshot_id as string | undefined) ??
                      (run?.result?.context_snapshot_id as string | null | undefined),
                  },
                });
              }}>
              <h3 className='text-sm font-medium'>결정 기록 · {decision.scenario.title}</h3>
              <label className='grid gap-1 text-xs'>
                선택한 이유
                <Textarea required value={decision.rationale} onChange={e => setDecision({ ...decision, rationale: e.target.value })} />
              </label>
              <label className='grid gap-1 text-xs'>
                기대 결과
                <Textarea value={decision.expected} onChange={e => setDecision({ ...decision, expected: e.target.value })} />
              </label>
              <label className='grid gap-1 text-xs'>
                돌아볼 날짜
                <Input type='date' value={decision.reviewOn} onChange={e => setDecision({ ...decision, reviewOn: e.target.value })} />
              </label>
              {recordDecision.error && <Alert variant='destructive'>{errorMessage(recordDecision.error)}</Alert>}
              <div className='flex gap-2'>
                <Button type='submit' size='sm' disabled={recordDecision.isPending || !decision.rationale.trim()}>
                  결정 저장
                </Button>
                <Button type='button' size='sm' onClick={() => setDecision(null)}>
                  닫기
                </Button>
              </div>
            </form>
          )}
        </TabsContent>
        <TabsContent value='evidence' className='mt-0'>
          <ContextInspector {...inspector} onBack={onBack} />
        </TabsContent>
        <TabsContent value='actions' className='mt-0 grid gap-3 p-3'>
          {proposals.error ? (
            <Alert variant='destructive'>{errorMessage(proposals.error)}</Alert>
          ) : proposals.isPending && conversationId !== null ? (
            <p className='text-xs text-faint'>불러오는 중…</p>
          ) : proposals.data?.length ? (
            proposals.data.map(proposal => <ProposalCard key={proposal.id} proposal={proposal} />)
          ) : (
            <p className='text-ui text-muted-foreground'>이 상담에서 나온, 승인을 기다리는 제안이 없습니다.</p>
          )}
        </TabsContent>
      </Tabs>
    </aside>
  );
}
