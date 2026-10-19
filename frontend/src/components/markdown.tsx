import Link from 'next/link';
import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { Badge } from '@/components/ui/badge';

import { TABLE_LABEL } from '@/lib/labels';

const REF = /\[([a-z_]+):(\d+)\]/g;
const REF_HREF = '#ref:';

// `[table:id]` evidence refs become links so they survive markdown parsing, then render as chips.
const withRefLinks = (text: string) =>
  text.replace(REF, (_m, table: string, id: string) => `[${TABLE_LABEL[table] ?? '기록'}](${REF_HREF}${table}:${id})`);

const chip = 'inline-flex items-center rounded-sm border bg-muted px-1.5 text-2xs leading-5 text-muted-foreground';

const componentsFor = (onDocumentRef?: (ref: string) => void, recordHref?: (table: string, id: number) => string | null): Components => ({
  // Model/document markdown must never contact an external image server.
  img: ({ alt }) => <span className='text-muted-foreground'>[외부 이미지 차단{alt ? `: ${alt}` : ''}]</span>,
  a: ({ href, children }) => {
    if (href?.startsWith(`${REF_HREF}document_chunks:`))
      return (
        <button
          type='button'
          className={`${chip} cursor-pointer text-primary hover:bg-accent`}
          onClick={() => onDocumentRef?.(href.slice(REF_HREF.length))}
          title='답변에 쓴 문서 발췌 보기'>
          {children}
        </button>
      );
    if (href?.startsWith(REF_HREF)) {
      const [table, id] = href.slice(REF_HREF.length).split(':');
      const target = recordHref?.(table, Number(id));
      return target ? (
        <Link href={target} className={`${chip} text-primary hover:bg-accent`} title='근거 기록 열기'>
          {children}
        </Link>
      ) : (
        <Badge variant='ref' title='근거 기록'>
          {children}
        </Badge>
      );
    }
    return (
      <a href={href} target='_blank' rel='noreferrer'>
        {children}
      </a>
    );
  },
});

/** Advisor answers. react-markdown never renders raw HTML, so model output cannot inject markup. */
export function Markdown({
  text,
  onDocumentRef,
  recordHref,
}: {
  text: string;
  onDocumentRef?: (ref: string) => void;
  /** Where a `[table:id]` evidence chip links to; unmapped tables stay plain chips. */
  recordHref?: (table: string, id: number) => string | null;
}) {
  return (
    <div className='markdown'>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={componentsFor(onDocumentRef, recordHref)}>
        {withRefLinks(text)}
      </ReactMarkdown>
    </div>
  );
}
