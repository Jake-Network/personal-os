import type { CashflowColumnMapping } from '@/api-client/model';

/** Korean bank exports are often EUC-KR (CP949); UTF-8 is tried first and must decode cleanly. */
export function decodeCsvBytes(bytes: ArrayBuffer): string {
  try {
    return new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  } catch {
    return new TextDecoder('euc-kr').decode(bytes);
  }
}

function splitLine(line: string, delimiter: string): string[] {
  const cells: string[] = [];
  let cell = '';
  let quoted = false;
  for (let i = 0; i < line.length; i++) {
    const char = line[i];
    if (char === '"') {
      if (quoted && line[i + 1] === '"') {
        cell += '"';
        i++;
      } else quoted = !quoted;
    } else if (char === delimiter && !quoted) {
      cells.push(cell.trim());
      cell = '';
    } else cell += char;
  }
  cells.push(cell.trim());
  return cells;
}

/** Header cells after `skipRows` preamble lines, for the mapping dropdowns only; the server parses the file. */
export function headerColumns(text: string, skipRows: number): string[] {
  const header = text.replace(/^﻿/, '').split(/\r?\n/)[skipRows] ?? '';
  if (!header.trim()) return [];
  const delimiter = [',', '\t', ';'].reduce((best, d) => (header.split(d).length > header.split(best).length ? d : best), ',');
  return splitLine(header, delimiter).filter(Boolean);
}

const GUESSES: [keyof CashflowColumnMapping, RegExp][] = [
  ['date', /^(거래\s*일(자|시)?|이용\s*일(자|시)?|일자|날짜|거래일시|date)$/i],
  ['debit', /^(출금(액|금액)?|지급(액|금액)?|찾으신\s*금액|withdrawal|debit)$/i],
  ['credit', /^(입금(액|금액)?|맡기신\s*금액|deposit|credit)$/i],
  ['amount', /^(금액|이용\s*금액|결제\s*금액|거래\s*금액|amount)$/i],
  ['description', /^(적요|가맹점(명)?|이용\s*(가맹점|내역)|내용|거래\s*내용|기재\s*내용|description|memo)$/i],
  ['category', /^(분류|카테고리|업종|category)$/i],
];

/** Best-effort first mapping from common Korean and English header names; the user confirms it. */
export function guessMapping(columns: string[]): Partial<CashflowColumnMapping> {
  const mapping: Partial<CashflowColumnMapping> = {};
  for (const [field, pattern] of GUESSES) {
    const column = columns.find(c => pattern.test(c.trim()) && !Object.values(mapping).includes(c));
    if (column) mapping[field] = column;
  }
  // One amount shape only: debit/credit columns take precedence over a generic amount.
  if (mapping.debit || mapping.credit) delete mapping.amount;
  return mapping;
}

/** A filename-derived source ID: re-importing the same account should reuse it. */
export function sourceIdFrom(name: string): string {
  const slug = name
    .replace(/\.[^.]+$/, '')
    .replace(/[^A-Za-z0-9_-]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 60);
  return slug || 'csv';
}
