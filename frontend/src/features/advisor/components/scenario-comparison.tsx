import type { ScenarioView } from '@/api-client/model';
import { advisorLabel, advisorValue } from '../presentation';

const display = (value: unknown) => advisorValue(value);

/** Uses only saved backend results. Missing comparison values remain explicitly unknown. */
export function ScenarioComparison({ scenarios }: { scenarios: ScenarioView[] }) {
  if (!scenarios.length) return null;
  const metrics = [...new Set(scenarios.flatMap(scenario => Object.keys(scenario.results)))];
  return (
    <section className='mx-auto w-full max-w-[760px]' aria-label='대안 비교'>
      <h3 className='mb-1.5 text-ui font-semibold'>대안 비교</h3>
      <div className='hidden overflow-x-auto sm:block'>
        <table className='w-full table-fixed rounded-lg border bg-card text-left text-xs'>
          <thead>
            <tr>
              <th className='w-24 border-b p-2'>평가 항목</th>
              {scenarios.map(scenario => (
                <th key={scenario.id} className='border-b p-2'>
                  {scenario.title}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {metrics.map(metric => (
              <tr key={metric}>
                <th className='break-words border-b p-2 font-normal'>{advisorLabel(metric)}</th>
                {scenarios.map(scenario => (
                  <td key={scenario.id} className='break-words border-b p-2'>
                    {display(scenario.results[metric])}
                  </td>
                ))}
              </tr>
            ))}
            <tr>
              <th className='p-2 font-normal text-warning'>확인 안 된 것</th>
              {scenarios.map(scenario => (
                <td key={scenario.id} className='p-2'>
                  {scenario.unknowns.map(display).join(', ') || '없음'}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      </div>
      <div className='grid gap-3 sm:hidden'>
        {scenarios.map(scenario => (
          <article key={scenario.id} className='rounded-lg border bg-card p-2.5'>
            <h4 className='mb-2 text-sm font-medium'>{scenario.title}</h4>
            <dl className='grid gap-2 text-xs'>
              {metrics.map(metric => (
                <div key={metric}>
                  <dt className='text-muted-foreground'>{advisorLabel(metric)}</dt>
                  <dd>{display(scenario.results[metric])}</dd>
                </div>
              ))}
            </dl>
            <p className='mt-2 text-xs'>미확인 사항: {scenario.unknowns.map(display).join(', ') || '없음'}</p>
          </article>
        ))}
      </div>
    </section>
  );
}
