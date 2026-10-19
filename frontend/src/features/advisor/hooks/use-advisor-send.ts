'use client';

import { useEffect, useMemo, useRef, useState } from 'react';

import { useQueryClient } from '@tanstack/react-query';

import { ApiError, errorMessage } from '@/api-client/api-error';
import { createConversation, getListConversationsQueryKey, previewContext } from '@/api-client/generated/advisor/advisor';
import { getListProposalsQueryKey } from '@/api-client/generated/proposals/proposals';
import type { Category, ConversationCreateDomain, RunCreate } from '@/api-client/model';

import { workspaceApi, workspaceKey } from '../api';
import type { InspectorData, InspectorMode } from '../types';
import { optionsFor } from '../utils';
import { type DraftOptions, documentOptionsOf, initialDraft, type PendingRequest, planRunRequest, SUBMIT_BLOCK_MESSAGE, submitBlock } from '../utils/send-logic';
import { isUnfinished, type useWorkspace } from './use-workspace';

type Workspace = ReturnType<typeof useWorkspace>;

interface Options {
  conversationId: number | null;
  domain?: ConversationCreateDomain;
  documentParam: string | null;
  workspace: Workspace;
  providerNeedsSetup: boolean;
  privacyBlocked: Category[];
  onInspector: (data: InspectorData | null, mode: InspectorMode, loading?: boolean) => void;
  onConversationCreated?: (id: number) => void;
  /** After a send is saved: jump back to the latest messages. */
  onSaved: () => void;
}

/**
 * The composer's draft and the send path. A run is created once per request ID; an uncertain save is
 * reconciled with the server before a changed question goes out. The view remounts per conversation,
 * so a draft never leaks into another one.
 */
export function useAdvisorSend({
  conversationId,
  domain,
  documentParam,
  workspace,
  providerNeedsSetup,
  privacyBlocked,
  onInspector,
  onConversationCreated,
  onSaved,
}: Options) {
  const queryClient = useQueryClient();
  const [input, setInput] = useState('');
  const [draft, setDraft] = useState<DraftOptions>(() => initialDraft(conversationId, documentParam));
  const [sending, setSending] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [uncertainRetry, setUncertainRetry] = useState(false);
  const [previewState, setPreviewState] = useState<{ key: string; base?: InspectorData; data?: InspectorData; error?: string } | null>(null);
  const [forcedOn, setForcedOn] = useState<Set<Category>>(new Set());
  const [forcedOff, setForcedOff] = useState<Set<Category>>(new Set());
  const pendingRequest = useRef<PendingRequest | null>(null);
  const pendingResponse = useRef<{ key: string; requestId: string } | null>(null);
  const sendLock = useRef(false);
  const createdConversation = useRef<number | null>(null);
  const inspectorRef = useRef(onInspector);
  useEffect(() => {
    inspectorRef.current = onInspector;
  });

  const activeRun = workspace.data?.active_run;
  const busy = sending || isUnfinished(activeRun?.status);
  const waiting = activeRun?.status === 'waiting_input' && !!activeRun.clarification;

  const documentOptions = useMemo(() => documentOptionsOf(draft), [draft]);
  const previewKey = JSON.stringify([input.trim(), conversationId, documentOptions, [...forcedOn], [...forcedOff]]);
  const baseline = previewState?.key === previewKey ? previewState.base : undefined;
  const preview = previewState?.key === previewKey ? previewState.data : undefined;
  const previewError = previewState?.key === previewKey ? previewState.error : undefined;
  const requestOptions = baseline ? optionsFor(baseline, forcedOn, forcedOff) : { exclude: [...forcedOff] };

  // Debounced context preview while typing (nothing is sent to the model).
  useEffect(() => {
    let current = true;
    const text = input.trim();
    if (busy) return;
    if (!text) {
      inspectorRef.current(workspace.context ?? null, workspace.context ? 'answer' : 'preview');
      return;
    }
    inspectorRef.current(null, 'preview');
    if (text.length < 2 || (draft.webSearch && !draft.webQuery.trim())) return;
    const timer = setTimeout(async () => {
      try {
        const base = (await previewContext({ message: text, conversation_id: conversationId, ...documentOptions })) as InspectorData;
        if (!current) return;
        const adjusted = forcedOn.size || forcedOff.size;
        const final = adjusted
          ? ((await previewContext({
              message: text,
              conversation_id: conversationId,
              ...optionsFor(base, forcedOn, forcedOff),
              ...documentOptions,
            })) as InspectorData)
          : base;
        if (!current) return;
        setPreviewState({ key: previewKey, base, data: final });
        inspectorRef.current(final, 'preview');
      } catch (error) {
        if (current) setPreviewState({ key: previewKey, error: '공유 범위를 미리 확인하지 못했습니다. ' + errorMessage(error) });
      }
    }, 350);
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [input, conversationId, forcedOn, forcedOff, busy, documentOptions, draft.webSearch, draft.webQuery, previewKey, workspace.context]);

  function toggleCategory(c: Category) {
    if (privacyBlocked.includes(c) || c === 'profile') return;
    const isOn = preview?.categories.includes(c);
    const on = new Set(forcedOn);
    const off = new Set(forcedOff);
    if (isOn) {
      if (on.has(c)) on.delete(c);
      else off.add(c);
    } else {
      if (off.has(c)) off.delete(c);
      else on.add(c);
    }
    setForcedOn(on);
    setForcedOff(off);
  }

  const updateDraft = (patch: Partial<DraftOptions>) => setDraft(d => ({ ...d, ...patch }));

  async function send(textArg?: string) {
    const text = (textArg ?? input).trim();
    const block = submitBlock({
      text,
      locked: sendLock.current,
      sending,
      busy,
      waiting,
      providerNeedsSetup,
      forcedOnCount: forcedOn.size,
      hasBaseline: !!baseline,
      webSearch: draft.webSearch,
      webQuery: draft.webQuery,
    });
    if (block && block !== 'share_pending' && block !== 'web_query') return;
    // A suggestion or option outside a clarification only fills the box; the user reviews sharing first.
    if (textArg && !waiting && text !== input.trim()) {
      setInput(text);
      return;
    }
    if (block) {
      setLoadError(SUBMIT_BLOCK_MESSAGE[block] ?? null);
      return;
    }
    sendLock.current = true;
    setSending(true);
    setLoadError(null);
    let convId = conversationId ?? createdConversation.current;
    let runSaved = false;
    try {
      if (convId === null) {
        const conv = await createConversation({ title: text.slice(0, 60), domain: domain ?? null });
        convId = conv.id;
        createdConversation.current = conv.id;
        void queryClient.invalidateQueries({ queryKey: getListConversationsQueryKey() });
      }
      if (waiting && activeRun?.clarification) {
        const key = `${activeRun.id}:${activeRun.revision}:${text}`;
        if (pendingResponse.current?.key !== key) pendingResponse.current = { key, requestId: crypto.randomUUID() };
        await workspaceApi.respond(activeRun.id, {
          request_id: pendingResponse.current.requestId,
          question_id: activeRun.clarification.id,
          expected_revision: activeRun.revision,
          response: text,
        });
        pendingResponse.current = null;
      } else {
        const previous = pendingRequest.current;
        const candidate: RunCreate = {
          message: text,
          ...requestOptions,
          ...documentOptions,
          request_id: crypto.randomUUID(),
          depth: draft.depth,
          parent_revision: workspace.data?.revision,
        };
        const plan = planRunRequest(previous, candidate, convId);
        if (plan.action === 'reconcile' && previous) {
          // Reconcile an uncertain save before creating a request with changed settings.
          const recovered = await workspaceApi.get(convId);
          queryClient.setQueryData(workspaceKey(convId), recovered);
          const accepted = [recovered.active_run, recovered.latest_run].some(run => run?.request_id === previous.body.request_id);
          if (accepted) {
            pendingRequest.current = null;
            onSaved();
            throw new Error('이전 질문은 이미 접수되었습니다. 답변을 확인한 뒤 바꾼 설정으로 다시 보내 주세요.');
          }
          if (isUnfinished(recovered.active_run?.status)) throw new Error('진행 중인 상담이 끝난 뒤 다시 보내 주세요.');
          setUncertainRetry(true);
          throw new Error('이전 질문이 접수됐는지 아직 확인되지 않았습니다. 바꾼 질문을 따로 보내면 두 질문이 모두 처리될 수 있습니다.');
        }
        const body = plan.action === 'send' ? plan.body : candidate;
        pendingRequest.current = { conversationId: convId, body };
        await workspaceApi.createRun(convId, body);
        pendingRequest.current = null;
      }
      runSaved = true;
      setUncertainRetry(false);
      onSaved();
      setInput('');
      if (!waiting) updateDraft({ webSearch: false, webQuery: '' });
      setForcedOn(new Set());
      setForcedOff(new Set());
      setPreviewState(null);
      await queryClient.invalidateQueries({ queryKey: workspaceKey(convId) });
    } catch (e) {
      // Validation/auth rejection cannot have created this run. Conflict/network/5xx remain uncertain.
      if (e instanceof ApiError && [401, 403, 422].includes(e.status)) pendingRequest.current = null;
      setLoadError(errorMessage(e));
      if (convId) void queryClient.invalidateQueries({ queryKey: workspaceKey(convId) });
      if (conversationId === null && convId !== null) {
        try {
          const recovered = await workspaceApi.get(convId);
          runSaved = !!(recovered.active_run ?? recovered.latest_run);
        } catch {
          /* Keep the draft and request identity for an explicit retry. */
        }
      }
    } finally {
      sendLock.current = false;
      setSending(false);
      if (runSaved && conversationId === null && convId !== null) onConversationCreated?.(convId);
      void queryClient.invalidateQueries({ queryKey: getListConversationsQueryKey() });
      void queryClient.invalidateQueries({ queryKey: getListProposalsQueryKey() });
    }
  }

  /** The user chose to send the changed question as a separate request despite the uncertain earlier one. */
  function sendSeparately() {
    pendingRequest.current = null;
    setUncertainRetry(false);
    void send();
  }

  const canSend =
    submitBlock({
      text: input,
      locked: false,
      sending,
      busy,
      waiting,
      providerNeedsSetup,
      forcedOnCount: 0,
      hasBaseline: true,
      webSearch: draft.webSearch,
      webQuery: draft.webQuery,
    }) === null &&
    !workspace.error &&
    !(conversationId !== null && workspace.isPending);

  return {
    input,
    setInput,
    draft,
    updateDraft,
    preview,
    previewError,
    forcedOff,
    toggleCategory,
    send,
    sendSeparately,
    sending,
    busy,
    waiting,
    canSend,
    loadError,
    uncertainRetry,
  };
}

export type AdvisorSend = ReturnType<typeof useAdvisorSend>;
