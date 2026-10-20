'use client';

import { useState } from 'react';

import { useQueryClient } from '@tanstack/react-query';
import { Check, Copy, FileSearch } from 'lucide-react';
import Link from 'next/link';

import { errorMessage } from '@/api-client/api-error';
import { getGetSnapshotQueryOptions } from '@/api-client/generated/advisor/advisor';
import { Markdown } from '@/components/markdown';
import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { ERROR_HINT } from '@/lib/labels';
import { cn } from '@/lib/utils';
import { dateOnly, dateTime } from '@/lib/utils/format';

import type { DocumentCitation } from '@/features/documents/api';

import { evidenceHref } from '../consts';
import type { ChatMessage } from '../types';
import { snapshotToInspector, stripBlocks } from '../utils';
import { MemoryProposalCard, ProposalCard } from './proposal-card';
import { AnswerActions } from './answer-actions';

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      size='icon-sm'
      variant='ghost'
      aria-label={copied ? '복사했습니다' : '답변 복사'}
      onClick={() =>
        void navigator.clipboard?.writeText(text).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        })
      }>
      {copied ? <Check /> : <Copy />}
    </Button>
  );
}

export function MessageItem({
  message: m,
  compact,
  conversationId,
  question,
  highlighted,
  onEvidence,
  onDocument,
}: {
  message: ChatMessage;
  compact?: boolean;
  conversationId?: number | null;
  question?: string;
  highlighted?: boolean;
  onEvidence: (message: ChatMessage) => void;
  onDocument: (message: ChatMessage, ref: string) => void;
}) {
  const assistant = m.role === 'assistant';
  return (
    <div id={m.id ? `message-${m.id}` : undefined} className='mx-auto w-full max-w-[760px]'>
      {(m.content || m.streaming) && (
        <div
          className={cn(
            'rounded-lg px-3.5 py-2.5',
            assistant ? cn('border', compact ? 'bg-background' : 'bg-card') : 'ml-auto w-fit max-w-[80%] whitespace-pre-wrap bg-accent',
            highlighted && 'ring-2 ring-primary/60',
          )}>
          {assistant ? (
            m.content ? (
              <div className={m.streaming ? 'typing' : undefined}>
                <Markdown
                  text={m.streaming ? stripBlocks(m.content) : m.content}
                  onDocumentRef={ref => onDocument(m, ref)}
                  recordHref={evidenceHref}
                />
              </div>
            ) : (
              <span className='typing text-xs text-faint'>기록을 살펴보고 답변을 준비하는 중</span>
            )
          ) : (
            m.content
          )}
        </div>
      )}
      {m.error && (
        <Alert variant='destructive' className='mt-1.5'>
          <span className='flex-1'>{m.error.message}</span>
          {ERROR_HINT[m.error.code] && (
            <Button asChild size='sm'>
              <Link href={ERROR_HINT[m.error.code].href}>{ERROR_HINT[m.error.code].action}</Link>
            </Button>
          )}
        </Alert>
      )}
      <div className={cn('mt-1 flex min-h-7 flex-wrap items-center gap-1 text-2xs text-faint', !assistant && 'justify-end')}>
        {m.created_at && <span>{dateTime(m.created_at)}</span>}
        {m.status === 'incomplete' && <Badge variant='warning'>답변이 끝나지 않음</Badge>}
        {!assistant && m.status === 'failed' && <Badge>답변 없음</Badge>}
        {assistant && !m.streaming && m.context_snapshot_id && (
          <Button size='sm' variant='ghost' aria-pressed={highlighted} onClick={() => onEvidence(m)} className='text-2xs'>
            <FileSearch /> 근거
          </Button>
        )}
        {assistant && !m.streaming && m.content && <CopyButton text={m.content} />}
        {assistant && m.is_final_answer && m.id && conversationId && !m.streaming && m.status === 'complete' && (
          <AnswerActions messageId={m.id} conversationId={conversationId} question={question ?? ''} />
        )}
      </div>
      {m.proposals?.length || m.memoryProposals?.length ? (
        <div className='mt-2 flex flex-col gap-2.5'>
          {m.proposals?.map(p => (
            <ProposalCard key={p.id} proposal={p} />
          ))}
          {m.memoryProposals?.map(p => (
            <MemoryProposalCard key={p.id} memory={p} />
          ))}
        </div>
      ) : null}
    </div>
  );
}

/** The saved excerpt a document citation points at, as it was when the answer was written. */
export function useDocumentSource() {
  const queryClient = useQueryClient();
  const [source, setSource] = useState<{ citation?: DocumentCitation; error?: string; loading?: boolean } | null>(null);

  async function show(message: ChatMessage, ref: string) {
    setSource({ loading: true });
    try {
      const snapshot = message.context_snapshot_id
        ? await queryClient.fetchQuery({ ...getGetSnapshotQueryOptions(message.context_snapshot_id), staleTime: 0 })
        : null;
      const citations = snapshot ? snapshotToInspector(snapshot).document_citations : message.document_citations;
      const citation = citations?.find(c => c.ref.replace(/^\[|\]$/g, '') === ref);
      setSource(citation ? { citation } : { error: '이 답변의 근거가 삭제되었거나 보관된 발췌가 없습니다.' });
    } catch (e) {
      setSource({ error: errorMessage(e) });
    }
  }

  const dialog = (
    <Dialog open={source !== null} onOpenChange={open => !open && setSource(null)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{source?.citation?.title ?? '문서 근거'}</DialogTitle>
          {source?.citation && (
            <DialogDescription>
              {source.citation.filename}
              {source.citation.page ? ` · ${source.citation.page}쪽` : ''}
              {source.citation.section ? ` · ${source.citation.section}` : ''}
              {source.citation.as_of ? ` · 기준일 ${dateOnly(source.citation.as_of)}` : ''}
              {source.citation.historical ? ' · 이전 상담에서 쓴 이전 판' : ' · 답변 당시 발췌'}
            </DialogDescription>
          )}
        </DialogHeader>
        {source?.loading && <p className='text-ui text-muted-foreground'>불러오는 중…</p>}
        {source?.error && <p className='text-ui'>{source.error}</p>}
        {source?.citation && <div className='max-h-[60vh] overflow-y-auto whitespace-pre-wrap text-sm'>{source.citation.text}</div>}
      </DialogContent>
    </Dialog>
  );
  return { show, dialog };
}
