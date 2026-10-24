'use client';

import { useState } from 'react';

import { useQueryClient } from '@tanstack/react-query';

import { errorMessage } from '@/api-client/api-error';
import { useCreatePlaybook, useRevisePlaybook } from '@/api-client/generated/playbooks/playbooks';
import type { Category, PlaybookRevisionItem } from '@/api-client/model';
import { notify } from '@/components/notify';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { ALL_CATEGORIES, CATEGORY_LABEL } from '@/lib/labels';

import { FINDING_LABEL, invalidatePlaybooks, splitTriggers } from '../consts';

interface Props {
  open: boolean;
  onClose: () => void;
  /** Editing an approved playbook creates a new version based on this one. */
  base?: { playbookId: number; revision: PlaybookRevisionItem };
}

export function PlaybookEditor({ open, onClose, base }: Props) {
  const queryClient = useQueryClient();
  const current = base?.revision;
  const [slug, setSlug] = useState('');
  const [title, setTitle] = useState(current?.title ?? '');
  const [summary, setSummary] = useState(current?.summary ?? '');
  const [triggers, setTriggers] = useState(current?.triggers.join(', ') ?? '');
  const [categories, setCategories] = useState<string[]>(current?.categories ?? []);
  const [body, setBody] = useState(current?.body ?? '');
  const done = async (warnings: string[]) => {
    await invalidatePlaybooks(queryClient);
    if (warnings.length) notify.info(`저장했습니다. 확인할 내용: ${warnings.map(w => FINDING_LABEL[w] ?? w).join(', ')}`);
    else notify.success('플레이북을 저장했습니다');
    onClose();
  };
  const create = useCreatePlaybook({ mutation: { onSuccess: result => done(result.active_revision?.warnings ?? []) } });
  const revise = useRevisePlaybook({ mutation: { onSuccess: result => done(result.warnings) } });
  const busy = create.isPending || revise.isPending;
  const error = create.error ?? revise.error;

  const submit = () => {
    const content = { title, summary, body, triggers: splitTriggers(triggers), categories: categories as Category[] };
    if (base) revise.mutate({ playbookId: base.playbookId, data: { ...content, base_revision_id: base.revision.id } });
    else create.mutate({ data: { ...content, slug: slug.trim() } });
  };

  return (
    <Dialog open={open} onOpenChange={o => !o && !busy && onClose()}>
      <DialogContent className='max-h-[90vh] w-[min(640px,calc(100%-32px))] overflow-y-auto'>
        <DialogHeader>
          <DialogTitle>{base ? '플레이북 수정' : '새 플레이북'}</DialogTitle>
          <DialogDescription className='text-ui text-muted-foreground'>
            상담에서 다시 쓸 확인 순서를 적습니다. 금액·날짜 같은 개인 기록 대신 무엇을 어떤 순서로 볼지 씁니다.
          </DialogDescription>
        </DialogHeader>
        <form
          className='flex flex-col gap-3'
          onSubmit={event => {
            event.preventDefault();
            submit();
          }}>
          {!base && (
            <div className='flex flex-col gap-1'>
              <Label htmlFor='playbook-slug'>짧은 이름</Label>
              <Input
                id='playbook-slug'
                required
                minLength={2}
                maxLength={40}
                pattern='[a-z0-9가-힣][a-z0-9가-힣\-]{1,39}'
                placeholder='예: 이직-점검'
                value={slug}
                onChange={e => setSlug(e.target.value)}
              />
              <p className='text-2xs text-faint'>상담 입력창에서 /짧은 이름 으로 바로 불러올 수 있습니다. 소문자·숫자·한글·하이픈만 씁니다.</p>
            </div>
          )}
          <div className='flex flex-col gap-1'>
            <Label htmlFor='playbook-title'>제목</Label>
            <Input id='playbook-title' required maxLength={120} value={title} onChange={e => setTitle(e.target.value)} />
          </div>
          <div className='flex flex-col gap-1'>
            <Label htmlFor='playbook-summary'>언제 쓰는지</Label>
            <Input id='playbook-summary' required maxLength={300} value={summary} onChange={e => setSummary(e.target.value)} />
          </div>
          <div className='flex flex-col gap-1'>
            <Label htmlFor='playbook-triggers'>자동으로 고를 단어</Label>
            <Input id='playbook-triggers' placeholder='쉼표로 구분 (예: 이직, 퇴사)' value={triggers} onChange={e => setTriggers(e.target.value)} />
          </div>
          <fieldset className='flex flex-col gap-1'>
            <legend className='mb-1 text-ui font-medium'>관련 영역</legend>
            <div className='flex flex-wrap gap-x-4 gap-y-1.5'>
              {ALL_CATEGORIES.map(category => (
                <label key={category} className='flex items-center gap-1.5 text-ui'>
                  <Checkbox
                    checked={categories.includes(category)}
                    onCheckedChange={checked =>
                      setCategories(previous => (checked === true ? [...previous, category] : previous.filter(c => c !== category)))
                    }
                  />
                  {CATEGORY_LABEL[category]}
                </label>
              ))}
            </div>
            <p className='text-2xs text-faint'>이 중 하나라도 공유를 막으면 이 플레이북은 상담에 보내지 않습니다.</p>
          </fieldset>
          <div className='flex flex-col gap-1'>
            <Label htmlFor='playbook-body'>절차</Label>
            <Textarea id='playbook-body' required maxLength={8000} rows={10} value={body} onChange={e => setBody(e.target.value)} />
          </div>
          {error && <Alert variant='destructive'>{errorMessage(error)}</Alert>}
          <div className='flex justify-end gap-2'>
            <Button type='button' disabled={busy} onClick={onClose}>
              취소
            </Button>
            <Button type='submit' variant='primary' disabled={busy}>
              {busy ? '저장하는 중…' : base ? '새 버전으로 저장' : '저장'}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
