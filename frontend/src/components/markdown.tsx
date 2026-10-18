import ReactMarkdown, { type Components } from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { Badge } from '@/components/ui/badge';

import { TABLE_LABEL } from '@/lib/labels';

const REF = /\[([a-z_]+):(\d+)\]/g;
const REF_HREF = '#ref:';

// `[table:id]` evidence refs become links so they survive markdown parsing, then render as chips.
const withRefLinks = (text: string) =>
  text.replace(REF, (_m, table: string, id: string) => `[${TABLE_LABEL[table] ?? table} #${id}](${REF_HREF}${table}:${id})`);

const componentsFor = (onDocumentRef?: (ref: string) => void): Components => ({
  a: ({ href, children }) =>
    href?.startsWith(`${REF_HREF}document_chunks:`) ? (
      <button
        type='button'
        className='inline rounded border px-1 text-xs text-primary underline'
        onClick={() => onDocumentRef?.(href.slice(REF_HREF.length))}
        title='답변에 사용한 문서 발췌문 보기'>
        {children}
      </button>
    ) : href?.startsWith(REF_HREF) ? (
      <Badge variant='ref' title={`근거 레코드 ${href.slice(REF_HREF.length)}`}>
        {children}
      </Badge>
    ) : (
      <a href={href} target='_blank' rel='noreferrer'>
        {children}
      </a>
    ),
});

/** Advisor answers. react-markdown never renders raw HTML, so model output cannot inject markup. */
export function Markdown({ text, onDocumentRef }: { text: string; onDocumentRef?: (ref: string) => void }) {
  return (
    <div className='markdown'>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={componentsFor(onDocumentRef)}>
        {withRefLinks(text)}
      </ReactMarkdown>
    </div>
  );
}
