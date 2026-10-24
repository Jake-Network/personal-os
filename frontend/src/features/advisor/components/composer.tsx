'use client';

import { useState } from 'react';

import { useQuery } from '@tanstack/react-query';
import { ChevronDown, FileText, Globe, History, Microscope, MoreHorizontal, SendHorizontal, ShieldCheck } from 'lucide-react';
import Link from 'next/link';

import type { Category } from '@/api-client/model';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Switch } from '@/components/ui/switch';
import { Textarea } from '@/components/ui/textarea';
import { ALL_CATEGORIES, CATEGORY_HINT, CATEGORY_LABEL } from '@/lib/labels';
import { cn } from '@/lib/utils';

import { documentsApi, documentsKey } from '@/features/documents/api';
import { RecordSelect } from '@/features/personal-data/components/record-select';

import type { AdvisorSend } from '../hooks/use-advisor-send';
import { MAX_DOCUMENTS } from '../utils/send-logic';

const toolClass =
  'inline-flex h-7 items-center gap-1 rounded-md border border-transparent px-2 text-xs text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-3.5';
const toolOn = 'border-input bg-accent text-accent-foreground hover:bg-accent';

/** What this question shares, summarized in one stable control; the toggles live in its popover. */
export function ShareSummary({ send, privacyBlocked }: { send: AdvisorSend; privacyBlocked: Category[] }) {
  const { preview, input } = send;
  const on = preview ? ALL_CATEGORIES.filter(c => preview.categories.includes(c)) : [];
  const label = !input.trim()
    ? '공유 범위'
    : !preview
      ? '공유 범위 확인 중'
      : on.length
        ? `${on
            .slice(0, 2)
            .map(c => CATEGORY_LABEL[c])
            .join('·')}${on.length > 2 ? ` 외 ${on.length - 2}` : ''} 공유`
        : '개인 기록 공유 안 함';
  return (
    <Popover>
      <PopoverTrigger className={cn(toolClass, 'min-w-28 justify-start')} aria-label={`이번 질문의 공유 범위: ${label}`}>
        <ShieldCheck />
        <span className='truncate'>{label}</span>
        <ChevronDown className='ml-auto' />
      </PopoverTrigger>
      <PopoverContent className='flex flex-col gap-2'>
        <p className='text-xs text-faint'>이번 질문에 함께 보낼 기록</p>
        {!preview && <p className='text-ui text-muted-foreground'>질문을 입력하면 보낼 기록이 여기에 표시됩니다.</p>}
        {preview &&
          ALL_CATEGORIES.map(c => {
            const blocked = privacyBlocked.includes(c);
            const checked = preview.categories.includes(c);
            const id = `share-${c}`;
            return (
              <div key={c} className='flex items-center gap-2'>
                <Switch id={id} checked={checked} disabled={blocked || c === 'profile' || send.busy} onCheckedChange={() => send.toggleCategory(c)} />
                <Label htmlFor={id} className={cn('flex-1', blocked && 'text-faint')}>
                  {CATEGORY_LABEL[c]}
                  <span className='block text-2xs font-normal text-faint'>
                    {c === 'profile'
                      ? '개인 프로필 공유는 기본 공유 설정에서 변경할 수 있습니다.'
                      : blocked
                        ? '데이터 공유 설정에서 제외됨'
                        : CATEGORY_HINT[c]}
                  </span>
                </Label>
              </div>
            );
          })}
        <Link href='/settings/privacy' className='text-xs text-primary hover:underline'>
          기본 공유 설정
        </Link>
      </PopoverContent>
    </Popover>
  );
}

function DocumentPicker({ send }: { send: AdvisorSend }) {
  const { draft, updateDraft, busy } = send;
  const [query, setQuery] = useState('');
  const documents = useQuery({ queryKey: documentsKey, queryFn: documentsApi.list });
  const shareable = (documents.data ?? []).filter(d => d.sharing_enabled && d.active_version_id);
  const shown = shareable.filter(d => d.title.toLowerCase().includes(query.trim().toLowerCase()));
  const ids = draft.documentIds ?? [];
  const label = !draft.documentSearch
    ? '문서 안 씀'
    : ids.length
      ? `문서 ${ids.length}개`
      : draft.documentIds === null
        ? '문서 선택 이어받기'
        : '문서 주제로 찾기';
  return (
    <Popover>
      <PopoverTrigger className={cn(toolClass, draft.documentSearch && ids.length > 0 && toolOn)} disabled={busy}>
        <FileText />
        {label}
      </PopoverTrigger>
      <PopoverContent className='flex flex-col gap-2'>
        <div className='flex items-center gap-2'>
          <Switch id='doc-search' checked={draft.documentSearch} onCheckedChange={v => updateDraft({ documentSearch: v })} />
          <Label htmlFor='doc-search' className='flex-1'>
            문서에서 근거 찾기
          </Label>
        </div>
        {draft.documentSearch && (
          <>
            <p className='text-2xs text-faint'>지정하지 않으면 질문 주제에 맞는 문서를 찾습니다. 최대 {MAX_DOCUMENTS}개까지 지정할 수 있습니다.</p>
            {shareable.length > 6 && (
              <Input placeholder='문서 찾기' value={query} onChange={e => setQuery(e.target.value)} aria-label='문서 이름으로 찾기' />
            )}
            <div className='flex max-h-56 flex-col gap-1 overflow-y-auto'>
              {documents.error && <p className='text-xs text-destructive'>문서 목록을 불러오지 못했습니다.</p>}
              {documents.isSuccess && shareable.length === 0 && <p className='text-xs text-faint'>공유할 수 있는 문서가 없습니다.</p>}
              {shown.map(d => {
                const checked = ids.includes(d.id);
                return (
                  <label key={d.id} className='flex cursor-pointer items-center gap-2 rounded-md px-1 py-1 hover:bg-muted'>
                    <Checkbox
                      checked={checked}
                      disabled={!checked && ids.length >= MAX_DOCUMENTS}
                      onCheckedChange={v => updateDraft({ documentIds: v === true ? [...ids, d.id] : ids.filter(id => id !== d.id) })}
                    />
                    <span className='truncate'>{d.title}</span>
                  </label>
                );
              })}
            </div>
            {draft.documentIds !== null && (
              <Button size='sm' variant='ghost' onClick={() => updateDraft({ documentIds: null })}>
                이전 문서 선택 이어받기
              </Button>
            )}
            <Button size='sm' variant='ghost' className='self-start' onClick={() => updateDraft({ documentIds: [] })}>
              지정 해제하고 주제로 찾기
            </Button>
          </>
        )}
        <Link href='/documents' className='text-xs text-primary hover:underline'>
          문서함
        </Link>
      </PopoverContent>
    </Popover>
  );
}

/** Narrow the search over past consultations to a company, project or decision. */
function HistoryScope({ send }: { send: AdvisorSend }) {
  const { draft, updateDraft, busy } = send;
  const count = [draft.historyCompany, draft.historyProject, draft.historyDecision].filter(Boolean).length;
  return (
    <Popover>
      <PopoverTrigger className={cn(toolClass, count > 0 && toolOn)} disabled={busy}>
        <History />
        과거 경험{count > 0 ? ` ${count}` : ''}
      </PopoverTrigger>
      <PopoverContent className='flex flex-col gap-2.5'>
        <p className='text-xs text-faint'>지난 상담에서 이 범위의 내용을 찾아 참고합니다.</p>
        <div className='flex flex-col gap-1'>
          <Label htmlFor='history-company'>회사</Label>
          <Input id='history-company' value={draft.historyCompany} onChange={e => updateDraft({ historyCompany: e.target.value })} />
        </div>
        <div className='flex flex-col gap-1'>
          <Label htmlFor='history-project'>프로젝트</Label>
          <RecordSelect
            id='history-project'
            fieldName='project_id'
            value={draft.historyProject}
            onChange={e => updateDraft({ historyProject: e.target.value })}
          />
        </div>
        <div className='flex flex-col gap-1'>
          <Label htmlFor='history-decision'>결정</Label>
          <RecordSelect
            id='history-decision'
            fieldName='decision_id'
            value={draft.historyDecision}
            onChange={e => updateDraft({ historyDecision: e.target.value })}
          />
        </div>
        {count > 0 && (
          <Button
            size='sm'
            variant='ghost'
            className='self-start'
            onClick={() => updateDraft({ historyCompany: '', historyProject: '', historyDecision: '' })}>
            범위 지우기
          </Button>
        )}
      </PopoverContent>
    </Popover>
  );
}

export function AutomaticRecordingToggle({ send }: { send: Pick<AdvisorSend, 'draft' | 'updateDraft' | 'busy'> }) {
  return (
    <div className='flex items-start gap-2 rounded-md px-2 py-1'>
      <Switch
        id='automatic-data-recording'
        checked={send.draft.allowDataRecording}
        disabled={send.busy}
        onCheckedChange={value => send.updateDraft({ allowDataRecording: value })}
        aria-describedby='automatic-data-recording-description'
      />
      <Label htmlFor='automatic-data-recording' className='flex-1 leading-snug'>
        자동 기록
        <span id='automatic-data-recording-description' className='mt-1 block text-2xs font-normal text-faint'>
          말한 실적·잔액·보유량을 기록합니다. 삭제는 직접 요청해야 합니다.
        </span>
      </Label>
    </div>
  );
}

export function Composer({
  send,
  compact,
  privacyBlocked,
  workspaceError,
  newMessages,
  onShowNew,
}: {
  send: AdvisorSend;
  compact?: boolean;
  privacyBlocked: Category[];
  workspaceError?: string | null;
  newMessages: boolean;
  onShowNew: () => void;
}) {
  const { draft, updateDraft, busy, waiting, sending } = send;
  return (
    <div className={cn('border-t bg-card', compact ? 'px-3 py-2.5' : 'px-4 pb-3 pt-2.5 md:px-5')}>
      <div className='mx-auto flex max-w-[760px] flex-col gap-2'>
        {newMessages && (
          <Button size='sm' className='self-center' onClick={onShowNew}>
            새 메시지 보기
          </Button>
        )}
        {send.loadError && <Alert variant='destructive'>{send.loadError}</Alert>}
        {send.uncertainRetry && (
          <Button className='self-start' disabled={busy} onClick={send.sendSeparately}>
            바꾼 질문 따로 보내기
          </Button>
        )}
        {workspaceError && <Alert variant='destructive'>상담 상태를 확인하지 못했습니다. {workspaceError}</Alert>}
        {send.previewError && (
          <p role='status' className='text-xs text-warning'>
            {send.previewError}
          </p>
        )}
        <div className='rounded-lg border bg-background focus-within:ring-2 focus-within:ring-ring'>
          <Textarea
            className='max-h-[200px] min-h-[52px] resize-none border-0 bg-transparent shadow-none focus-visible:ring-0'
            placeholder={
              waiting
                ? '위 질문에 답해 주세요'
                : busy
                  ? '분석하는 동안 다음 질문을 미리 써 둘 수 있습니다'
                  : '무엇이든 물어보세요. 예: 지금 퇴사해도 6개월 버틸 수 있을까?'
            }
            value={send.input}
            onChange={e => send.setInput(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                void send.send();
              }
            }}
            rows={2}
            aria-label={waiting ? '확인 질문에 답하기' : '질문 입력'}
          />
          <div className='flex flex-wrap items-center gap-1 px-2 pb-2'>
            {!waiting && (
              <>
                <ShareSummary send={send} privacyBlocked={privacyBlocked} />
                <button
                  type='button'
                  className={cn(toolClass, draft.depth === 'deep' && toolOn)}
                  aria-pressed={draft.depth === 'deep'}
                  disabled={busy}
                  onClick={() => updateDraft({ depth: draft.depth === 'deep' ? 'auto' : 'deep' })}>
                  <Microscope />
                  깊게 분석
                </button>
                <Popover>
                  <PopoverTrigger className={toolClass} disabled={busy}>
                    <MoreHorizontal />
                    더보기
                  </PopoverTrigger>
                  <PopoverContent className='flex flex-col items-start gap-2'>
                    <AutomaticRecordingToggle send={send} />
                    <DocumentPicker send={send} />
                    <HistoryScope send={send} />
                    <button
                      type='button'
                      className={cn(toolClass, draft.webSearch && toolOn)}
                      aria-pressed={draft.webSearch}
                      disabled={busy}
                      onClick={() => updateDraft({ webSearch: !draft.webSearch })}>
                      <Globe />웹 검색
                    </button>
                  </PopoverContent>
                </Popover>
              </>
            )}
            <Button variant='primary' size='sm' className='ml-auto' onClick={() => void send.send()} disabled={!send.canSend}>
              <SendHorizontal />
              {sending ? '보내는 중…' : waiting ? '답하기' : '보내기'}
            </Button>
          </div>
        </div>
        {!waiting && (
          <div className='flex flex-wrap gap-1 text-2xs text-muted-foreground'>
            {!draft.documentSearch ? (
              <span className='rounded border px-2 py-0.5'>문서 검색 끔</span>
            ) : (
              draft.documentIds !== null && (
                <span className='rounded border px-2 py-0.5'>
                  {draft.documentIds.length ? `지정 문서 ${draft.documentIds.length}개` : '문서 지정 해제 · 주제로 찾기'}
                </span>
              )
            )}
            {[draft.historyCompany, draft.historyProject, draft.historyDecision].some(Boolean) && (
              <span className='rounded border px-2 py-0.5'>과거 경험 범위 지정</span>
            )}
            {draft.webSearch && <span className='rounded border px-2 py-0.5'>웹 검색 사용</span>}
            {draft.allowDataRecording && <span className='rounded border border-primary/30 bg-accent px-2 py-0.5 text-accent-foreground'>자동 기록 켜짐</span>}
          </div>
        )}
        {draft.webSearch && !waiting && (
          <div className='flex flex-col gap-1'>
            <Input
              value={draft.webQuery}
              maxLength={300}
              disabled={busy}
              onChange={e => updateDraft({ webQuery: e.target.value })}
              placeholder='공개 검색어 (예: 회사명 백엔드 채용 공고)'
              aria-label='웹 검색어'
              aria-describedby='web-search-disclosure'
            />
            <span id='web-search-disclosure' className='text-2xs text-faint'>
              이 검색어만 외부 검색 서비스로 보냅니다. 개인정보는 넣지 마세요.
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
