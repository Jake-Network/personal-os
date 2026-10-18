import { customInstance } from '@/api-client/custom-client';
import type { ClarificationResponse, RunCreate, RunView, ScenarioCreate, ScenarioSelect, ScenarioView, WorkspaceView } from '@/api-client/model';

export const workspaceKey = (conversationId: number | null) => ['advisor-workspace', conversationId] as const;
const conversationPath = (id: number) => `/api/advisor/conversations/${id}`;
const runPath = (id: string) => `/api/advisor/runs/${id}`;

/** Inputs and results come from OpenAPI; transport retains the shared CSRF/error boundary. */
export const workspaceApi = {
  get: (id: number, signal?: AbortSignal) => customInstance<WorkspaceView>({ url: `${conversationPath(id)}/workspace`, signal }),
  createRun: (id: number, data: RunCreate) => customInstance<RunView>({ url: `${conversationPath(id)}/runs`, method: 'POST', data }),
  respond: (id: string, data: ClarificationResponse) => customInstance<RunView>({ url: `${runPath(id)}/responses`, method: 'POST', data }),
  cancel: (id: string) => customInstance<RunView>({ url: `${runPath(id)}/cancel`, method: 'POST' }),
  retry: (id: string) => customInstance<RunView>({ url: `${runPath(id)}/retry`, method: 'POST' }),
  createScenario: (id: number, data: ScenarioCreate) =>
    customInstance<ScenarioView>({ url: `${conversationPath(id)}/scenarios`, method: 'POST', data }),
  selectScenario: (id: number, data: ScenarioSelect) =>
    customInstance<WorkspaceView>({ url: `${conversationPath(id)}/scenarios/select`, method: 'POST', data }),
};
