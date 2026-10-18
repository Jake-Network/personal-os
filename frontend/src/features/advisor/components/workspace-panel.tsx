'use client';

import { useRef, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { errorMessage } from '@/api-client/api-error';
import { useListProposals } from '@/api-client/generated/proposals/proposals';
import { getListDecisionsQueryKey, useCreateDecision } from '@/api-client/generated/memory/memory';
import type { ScenarioView } from '@/api-client/model';
import { Alert } from '@/components/ui/alert';
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
import { RUN_LABEL } from './run-card';

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
    <article className='grid gap-2 rounded border p-3'>
      <div className='flex flex-wrap items-center gap-1'>
        <h3 className='text-sm font-medium'>{scenario.title}</h3>
        {selected && <Badge variant='accent'>후속 상담 기준</Badge>}
      </div>
      <p className='text-xs text-faint'>
        버전 {scenario.revision} · {dateTime(scenario.created_at)}
      </p>
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
          <p className='text-xs font-medium'>서버 계산 결과</p>
          <Values value={scenario.results} />
        </>
      )}
      {!!scenario.unknowns.length && <p className='text-xs text-warning'>확인 필요: {scenario.unknowns.map(String).join(', ')}</p>}
      {!!Object.keys(scenario.evidence).length && (
        <details className='text-xs'>
          <summary>결과 당시 근거 기준</summary>
          <Values value={scenario.evidence} />
        </details>
      )}
      <div className='flex flex-wrap gap-2'>
        <Button size='sm' disabled={busy || selected} onClick={onSelect}>
          이 대안으로 이어가기
        </Button>
        <Button size='sm' disabled={busy} onClick={() => setEditing(!editing)}>
          조건 바꿔 비교
        </Button>
        <Button size='sm' disabled={busy} onClick={onDecision}>
          결정으로 기록
        </Button>
      </div>
      {editing && (
        <div className='grid gap-2'>
          <Textarea
            aria-label={`${scenario.title} 변경할 조건`}
            placeholder='이번 비교에 적용할 조건을 입력하세요'
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
            새 버전으로 분석
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
}: {
  conversationId: number | null;
  inspector: { data: InspectorData | null; mode: InspectorMode; loading?: boolean };
  className?: string;
  onClose?: () => void;
}) {
  const workspace = useWorkspace(conversationId, false);
  const queryClient = useQueryClient();
  const evidenceKey = inspector.mode === 'snapshot' ? (inspector.data?.context_snapshot_id ?? 'loading') : 'preview';
  const [tabState, setTabState] = useState({ value: 'consultation', evidenceKey });
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
  const run = workspace.run;
  const busy = mutation.isPending || isUnfinished(workspace.data?.active_run?.status);
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
  return (
    <aside className={cn('min-h-0 overflow-y-auto border-l bg-card', className)} aria-label='상담 패널'>
      <div className='flex items-center justify-between border-b p-3'>
        <h2 className='font-medium'>상담 워크스페이스</h2>
        {onClose && (
          <Button size='sm' variant='ghost' onClick={onClose}>
            닫기
          </Button>
        )}
      </div>
      <Tabs value={tab} onValueChange={value => setTabState({ value, evidenceKey })} className='p-3'>
        <TabsList className='w-full'>
          <TabsTrigger value='consultation'>상담</TabsTrigger>
          <TabsTrigger value='evidence'>근거·기억</TabsTrigger>
          <TabsTrigger value='actions'>실행</TabsTrigger>
        </TabsList>
        <TabsContent value='consultation' className='grid gap-3'>
          {workspace.error && <Alert variant='destructive'>{errorMessage(workspace.error)}</Alert>}
          {mutation.error && <Alert variant='destructive'>{errorMessage(mutation.error)}</Alert>}
          {run && <Badge>{RUN_LABEL[run.status]}</Badge>}
          {!!Object.keys(workspace.data?.problem ?? {}).length && <Values value={workspace.data?.problem ?? {}} />}
          {!workspace.data?.scenarios?.length && <p className='text-xs text-faint'>상담에서 비교할 조건과 대안이 정리되면 여기에 표시합니다.</p>}
          {currentScenarios.length > 0 && (
            <>
              <h3 className='text-sm font-medium'>이번 비교</h3>
              {currentScenarios.map(renderScenario)}
            </>
          )}
          {historicalScenarios.length > 0 && (
            <details className='grid gap-3'>
              <summary className='mb-2 cursor-pointer text-sm'>과거 대안·조건 버전 ({historicalScenarios.length})</summary>
              <p className='mb-2 text-xs text-faint'>당시 근거의 기록입니다. 현재 비교와 기준 데이터가 다를 수 있습니다.</p>
              <div className='grid gap-3'>{historicalScenarios.map(renderScenario)}</div>
            </details>
          )}
          {decision && (
            <form
              className='grid gap-2 rounded border p-3'
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
              <h3 className='text-sm font-medium'>결정 기록: {decision.scenario.title}</h3>
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
        <TabsContent value='evidence'>
          <ContextInspector {...inspector} className='border-l-0' />
        </TabsContent>
        <TabsContent value='actions' className='grid gap-3'>
          {proposals.data?.length ? (
            proposals.data.map(proposal => <ProposalCard key={proposal.id} proposal={proposal} />)
          ) : (
            <p className='text-xs text-faint'>승인 대기 중인 행동 제안이 없습니다.</p>
          )}
          <p className='text-xs text-faint'>행동 제안은 승인 후에만 반영됩니다. 결정과 회고는 기존 결정 기록에서 관리합니다.</p>
        </TabsContent>
      </Tabs>
    </aside>
  );
}
