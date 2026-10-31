export const REVIEW_FILTERS = ['all', 'approvals', 'decisions', 'inbox'] as const;
export type ReviewFilter = (typeof REVIEW_FILTERS)[number];
