import * as pd from '@/api-client/generated/personal-data/personal-data';

export type Row = Record<string, unknown> & { id: number };
type Body = Record<string, unknown>;

export interface ResourceApi {
  queryKey: readonly unknown[];
  list: () => Promise<Row[]>;
  create: (body: Body) => Promise<unknown>;
  update: (id: number, body: Body) => Promise<unknown>;
  remove: (id: number) => Promise<unknown>;
}

// The data page is generic over resources and its form is built from the OpenAPI schema at runtime,
// so the generated per-resource body types are erased here.
/* eslint-disable @typescript-eslint/no-explicit-any */
const bind = (queryKey: readonly unknown[], list: () => Promise<any>, create: any, update: any, remove: any): ResourceApi => ({
  queryKey,
  list,
  create,
  update,
  remove,
});
/* eslint-enable @typescript-eslint/no-explicit-any */

export const RESOURCE_API: Record<string, ResourceApi> = {
  accounts: bind(pd.getListAccountsQueryKey(), pd.listAccounts, pd.createAccounts, pd.updateAccounts, pd.deleteAccounts),
  liabilities: bind(pd.getListLiabilitiesQueryKey(), pd.listLiabilities, pd.createLiabilities, pd.updateLiabilities, pd.deleteLiabilities),
  'other-assets': bind(pd.getListOtherAssetsQueryKey(), pd.listOtherAssets, pd.createOtherAssets, pd.updateOtherAssets, pd.deleteOtherAssets),
  'cashflow-entries': bind(
    pd.getListCashflowEntriesQueryKey(),
    pd.listCashflowEntries,
    pd.createCashflowEntries,
    pd.updateCashflowEntries,
    pd.deleteCashflowEntries,
  ),
  'planned-expenses': bind(
    pd.getListPlannedExpensesQueryKey(),
    pd.listPlannedExpenses,
    pd.createPlannedExpenses,
    pd.updatePlannedExpenses,
    pd.deletePlannedExpenses,
  ),
  holdings: bind(pd.getListHoldingsQueryKey(), pd.listHoldings, pd.createHoldings, pd.updateHoldings, pd.deleteHoldings),
  'fx-rates': bind(pd.getListFxRatesQueryKey(), pd.listFxRates, pd.createFxRates, pd.updateFxRates, pd.deleteFxRates),
  'job-applications': bind(
    pd.getListJobApplicationsQueryKey(),
    pd.listJobApplications,
    pd.createJobApplications,
    pd.updateJobApplications,
    pd.deleteJobApplications,
  ),
  interviews: bind(pd.getListInterviewsQueryKey(), pd.listInterviews, pd.createInterviews, pd.updateInterviews, pd.deleteInterviews),
  'career-criteria': bind(
    pd.getListCareerCriteriaQueryKey(),
    pd.listCareerCriteria,
    pd.createCareerCriteria,
    pd.updateCareerCriteria,
    pd.deleteCareerCriteria,
  ),
  'calendar-events': bind(
    pd.getListCalendarEventsQueryKey(),
    pd.listCalendarEvents,
    pd.createCalendarEvents,
    pd.updateCalendarEvents,
    pd.deleteCalendarEvents,
  ),
  tasks: bind(pd.getListTasksQueryKey(), pd.listTasks, pd.createTasks, pd.updateTasks, pd.deleteTasks),
  goals: bind(pd.getListGoalsQueryKey(), pd.listGoals, pd.createGoals, pd.updateGoals, pd.deleteGoals),
  'workout-logs': bind(pd.getListWorkoutLogsQueryKey(), pd.listWorkoutLogs, pd.createWorkoutLogs, pd.updateWorkoutLogs, pd.deleteWorkoutLogs),
};
