import { Fragment, type ReactNode } from 'react';
import { TABLE_LABEL } from '../lib/labels';

/**
 * Minimal, safe markdown for advisor answers: headings, lists, paragraphs, code, bold.
 * Builds React nodes only (no innerHTML). `[table:id]` evidence refs render as chips.
 */
export function Markdown({ text, onRef }: { text: string; onRef?: (ref: string) => void }) {
  const blocks: ReactNode[] = [];
  const lines = text.replace(/\r\n/g, '\n').split('\n');
  let i = 0;
  let key = 0;

  while (i < lines.length) {
    const line = lines[i];
    if (line.startsWith('```')) {
      const body: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith('```')) body.push(lines[i++]);
      i++;
      blocks.push(<pre key={key++}>{body.join('\n')}</pre>);
      continue;
    }
    const heading = /^#{1,6}\s+(.*)$/.exec(line);
    if (heading) {
      blocks.push(<h4 key={key++}>{inline(heading[1], onRef)}</h4>);
      i++;
      continue;
    }
    if (/^\s*[-*•]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*•]\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*[-*•]\s+/, ''));
      blocks.push(<ul key={key++}>{items.map((t, n) => <li key={n}>{inline(t, onRef)}</li>)}</ul>);
      continue;
    }
    if (/^\s*\d+[.)]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*\d+[.)]\s+/, ''));
      blocks.push(<ol key={key++}>{items.map((t, n) => <li key={n}>{inline(t, onRef)}</li>)}</ol>);
      continue;
    }
    if (!line.trim()) {
      i++;
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() && !/^(#{1,6}\s|```|\s*[-*•]\s|\s*\d+[.)]\s)/.test(lines[i])) {
      para.push(lines[i++]);
    }
    blocks.push(
      <p key={key++}>
        {para.map((p, n) => (
          <Fragment key={n}>
            {n > 0 && <br />}
            {inline(p, onRef)}
          </Fragment>
        ))}
      </p>,
    );
  }
  return <div className="md">{blocks}</div>;
}

const TOKEN = /(\*\*[^*]+\*\*|`[^`]+`|\[[a-z_]+:\d+\])/g;

function inline(text: string, onRef?: (ref: string) => void): ReactNode[] {
  return text.split(TOKEN).map((part, n) => {
    if (part.startsWith('**') && part.endsWith('**')) return <strong key={n}>{part.slice(2, -2)}</strong>;
    if (part.startsWith('`') && part.endsWith('`')) return <code key={n}>{part.slice(1, -1)}</code>;
    const ref = /^\[([a-z_]+):(\d+)\]$/.exec(part);
    if (ref) {
      const label = `${TABLE_LABEL[ref[1]] ?? ref[1]} #${ref[2]}`;
      return (
        <span key={n} className="chip ref" title={`근거 레코드 ${ref[1]}:${ref[2]}`} onClick={() => onRef?.(`${ref[1]}:${ref[2]}`)}>
          {label}
        </span>
      );
    }
    return <Fragment key={n}>{part}</Fragment>;
  });
}
