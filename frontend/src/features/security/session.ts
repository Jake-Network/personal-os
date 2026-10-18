// Session material lives only in memory; no personal data or credentials in browser storage.
let csrfToken: string | null = null;
const streams = new Set<AbortController>();
export const getCsrfToken = () => csrfToken;
export const setCsrfToken = (token: string | null) => {
  csrfToken = token;
};
export const registerPrivateStream = (controller: AbortController) => {
  streams.add(controller);
  return () => {
    streams.delete(controller);
  };
};
export function clearPrivateSession() {
  csrfToken = null;
  streams.forEach(controller => controller.abort());
  streams.clear();
}
export function notifySessionExpired() {
  clearPrivateSession();
  if (typeof window !== 'undefined') window.dispatchEvent(new Event('personal-os:locked'));
}
