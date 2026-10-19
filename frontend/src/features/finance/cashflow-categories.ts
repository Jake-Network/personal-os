export const CASHFLOW_CATEGORIES: Record<string, string[]> = {
  income: ['급여', '상여금', '사업소득', '부수입', '이자', '배당', '기타 수입'],
  expense: ['식비', '교통', '주거', '생활', '건강', '여가', '교육', '쇼핑', '기타 지출'],
};

export function cashflowCategories(kind: string): string[] {
  return CASHFLOW_CATEGORIES[kind] ?? Object.values(CASHFLOW_CATEGORIES).flat();
}
