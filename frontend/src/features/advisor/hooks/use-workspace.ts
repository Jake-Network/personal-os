'use client';

import { useEffect, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { getEventStream } from '@/api-client/event-stream';
import { getGetConversationQueryKey } from '@/api-client/generated/advisor/advisor';
import { getCountUnreadInboxQueryKey, getListInboxItemsQueryKey } from '@/api-client/generated/agent/agent';
import { getListPendingPlaybookRevisionsQueryKey } from '@/api-client/generated/playbooks/playbooks';
import { getListProposalsQueryKey } from '@/api-client/generated/proposals/proposals';
import type { RunEvent, RunView, WorkspaceView } from '@/api-client/model';
import { workspaceApi, workspaceKey } from '../api';
import type { InspectorData } from '../types';
import { applyRunEvent, type EventCursor } from '../run-events';

export const isUnfinished = (status?: RunView['status']) => !!status && !['completed', 'failed', 'cancelled'].includes(status);
export const isExecuting = (status?: RunView['status']) => !!status && ['queued', 'running', 'cancel_requested'].includes(status);

export function useWorkspace(conversationId: number | null, observe = true) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: workspaceKey(conversationId),
    queryFn: ({ signal }) => workspaceApi.get(conversationId!, signal),
    enabled: conversationId !== null,
    staleTime: 0,
    refetchInterval: data => (isExecuting(data.state.data?.active_run?.status) ? 1500 : 5000),
    refetchIntervalInBackground: false,
  });
  const run = query.data?.active_run ?? query.data?.latest_run;
  const runId = run?.id;
  const executing = isExecuting(run?.status);
  const [connection, setConnection] = useState<{ id?: string; reconnecting: boolean }>({ reconnecting: false });
  const [live, setLive] = useState<{ id?: string; revision: number; text: string }>({ revision: 0, text: '' });
  const [context, setContext] = useState<{ id: string; data: InspectorData } | null>(null);
  const [progress, setProgress] = useState<{ id: string; stage: string; message: string } | null>(null);

  useEffect(() => {
    if (!observe || !runId || !executing || conversationId === null) return;
    const controller = new AbortController();
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    // Replay persisted deltas once, then reconnect from the last accepted sequence.
    let cursor: EventCursor = { runId, seq: 0, answerRevision: run.answer_revision, text: '' };
    const refresh = () => queryClient.invalidateQueries({ queryKey: workspaceKey(conversationId) });
    const connect = async () => {
      try {
        await getEventStream<RunEvent>(
          `/api/advisor/runs/${runId}/events?after_seq=${cursor.seq}`,
          event => {
            if (controller.signal.aborted) return;
            const next = applyRunEvent(cursor, event);
            if (next.gap) throw new Error('상담 이벤트 누락: 저장된 위치에서 다시 연결합니다.');
            if (!next.accepted) return;
            cursor = next.cursor;
            setConnection({ id: runId, reconnecting: false });
            if (event.type === 'progress') {
              setProgress({
                id: runId,
                stage: String(event.payload.stage ?? ''),
                message: typeof event.payload.message === 'string' ? event.payload.message : '',
              });
            } else if (event.type === 'context') {
              setContext({ id: runId, data: event.payload as unknown as InspectorData });
            } else if (event.type === 'delta') {
              setLive({ id: runId, revision: cursor.answerRevision, text: cursor.text });
            } else {
              void refresh();
              void queryClient.invalidateQueries({ queryKey: getGetConversationQueryKey(conversationId) });
              // A finished run may complete a briefing notice or queue learning proposals.
              for (const queryKey of [getListProposalsQueryKey(), getCountUnreadInboxQueryKey(), getListInboxItemsQueryKey(), getListPendingPlaybookRevisionsQueryKey()])
                void queryClient.invalidateQueries({ queryKey });
            }
          },
          controller.signal,
        );
      } catch {
        if (controller.signal.aborted) return;
        setConnection({ id: runId, reconnecting: true });
        void refresh();
      }
      if (!controller.signal.aborted) retryTimer = setTimeout(() => void connect(), 1500);
    };
    void connect();
    return () => {
      controller.abort();
      clearTimeout(retryTimer);
    };
    // Cursor and revision belong to this subscription, not snapshot refreshes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, executing, conversationId, queryClient, observe]);

  useEffect(() => {
    if (!run || isExecuting(run.status) || conversationId === null) return;
    void queryClient.invalidateQueries({ queryKey: getGetConversationQueryKey(conversationId) });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run?.id, run?.status, conversationId, queryClient]);

  const refresh = () => queryClient.invalidateQueries({ queryKey: workspaceKey(conversationId) });
  const save = (view: WorkspaceView) => queryClient.setQueryData(workspaceKey(conversationId), view);
  return {
    data: query.data,
    error: query.error,
    isPending: query.isPending,
    run,
    refresh,
    save,
    progress: progress && progress.id === runId ? progress.stage : '',
    progressMessage: progress && progress.id === runId ? progress.message : '',
    context: context && context.id === runId ? context.data : (run?.result?.context as InspectorData | undefined),
    liveText: live.id === runId && live.revision === run?.answer_revision ? live.text : '',
    reconnecting: connection.id === runId && connection.reconnecting,
  };
}
