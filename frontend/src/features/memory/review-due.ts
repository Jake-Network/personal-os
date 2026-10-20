/** Shared by home and the journal: review is due at its scheduled instant. */
export function isDecisionReviewDue(decision: { reviewed_at?: string | null; review_on?: string | null }, now = Date.now()): boolean {
  return !decision.reviewed_at && !!decision.review_on && new Date(decision.review_on).getTime() <= now;
}
