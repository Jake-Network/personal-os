/**
 * Shared by home and the journal, and identical to the backend briefing signal: review is due at
 * its scheduled instant unless an outcome was recorded at or after it. An early outcome does not
 * settle a review scheduled later.
 */
export function isDecisionReviewDue(decision: { reviewed_at?: string | null; review_on?: string | null }, now = Date.now()): boolean {
  if (!decision.review_on) return false;
  const due = new Date(decision.review_on).getTime();
  if (!(due <= now)) return false;
  if (!decision.reviewed_at) return true;
  return new Date(decision.reviewed_at).getTime() < due;
}
