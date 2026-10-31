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

/**
 * The delimiter that splits the header into the most quote-aware cells; ties keep the earlier one.
 * Must match `_delimiter` in app/modules/finance/cashflow_import.py, or the dropdowns offer columns the server does not see.
 */
export function headerDelimiter(header: string): string {
  return [',', '\t', ';'].reduce((best, d) => (splitLine(header, d).length > splitLine(header, best).length ? d : best), ',');
}

/** Header cells after `skipRows` preamble lines, for the mapping dropdowns only; the server parses the file. */
export function headerColumns(text: string, skipRows: number): string[] {
  const header = text.replace(/^﻿/, '').split(/\r?\n/)[skipRows] ?? '';
  if (!header.trim()) return [];
  return splitLine(header, headerDelimiter(header)).filter(Boolean);
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

/** Stable 32-bit FNV-1a over UTF-8 bytes, so non-ASCII names keep distinct IDs. */
function shortHash(text: string): string {
  let hash = 0x811c9dc5;
  for (const byte of new TextEncoder().encode(text)) {
    hash ^= byte;
    hash = Math.imul(hash, 0x01000193) >>> 0;
  }
  return hash.toString(16).padStart(8, '0');
}

/**
 * A filename-derived source ID: re-importing the same account should reuse it.
 * The server accepts ASCII only, so a name with other characters (e.g. Korean card names) gets a hash
 * of the full name; otherwise '신한카드.csv' and '국민카드.csv' would share one ID and their rows would collide.
 */
export function sourceIdFrom(name: string): string {
  const base = name.replace(/\.[^.]+$/, '');
  const slug = base
    .replace(/[^A-Za-z0-9_-]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 50);
  if (/^[\x00-\x7F]*$/.test(base)) return slug || 'csv';
  return `${slug || 'csv'}-${shortHash(base.normalize('NFC'))}`;
}
