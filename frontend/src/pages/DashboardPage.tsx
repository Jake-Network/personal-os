import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { api } from '../api/client';
import type { DashboardSummary } from '../api/types';
import { AdvisorChat } from '../components/AdvisorChat';
import { useAsync } from '../lib/useAsync';
import { dateOnly, dateTime, money, moneyShort, relative } from '../lib/format';
import { flagDetail, flagText } from '../lib/labels';
import { enumLabel } from '../lib/resources';

export function DashboardPage() {
  const { data, error, loading } = useAsync(() => api<DashboardSummary>('/api/dashboard/summary'), []);
  const [panelConversation, setPanelConversation] = useState<number | null>(null);
  const navigate = useNavigate();

  const d = data?.data ?? {};
  const accounts = d.get_accounts_summary;
  const worth = accounts?.computed?.net_worth;
  const cash = d.get_cashflow_summary;
  const portfolio = d.get_portfolio_summary;
  const apps = d.get_job_applications?.applications ?? [];
  const interviews = d.get_interview_schedule?.interviews ?? [];
  const events = d.get_calendar_events?.events ?? [];
  const conflicts = d.get_calendar_events?.conflicts ?? [];
  const tasks = d.get_tasks?.open_tasks ?? [];
  const goals = d.get_goals?.active_goals ?? [];
  const health = d.get_health_summary;

  const expense = cash?.monthly_expense;
  const runwayMonths: string | null = data?.computed?.runway?.months ?? null;
  const importantFlags = (data?.data_quality_flags ?? []).filter((f) =>
    ['no_accounts', 'monthly_expense_unknown', 'net_worth_incomplete', 'stale_balance', 'stale_price', 'missing_fx'].includes(f.code),
  );

  return (
    <div className="page wide">
      <div className="dash">
        <div className="dash-main">
          <div className="page-head">
            <div>
              <h1>대시보드</h1>
              <p>{data ? `${dateTime(data.generated_at)} 기준 · 모든 수치는 백엔드 계산 결과입니다` : ' '}</p>
            </div>
            <Link to="/advisor" className="btn primary">AI 상담 열기</Link>
          </div>

          {error && <div className="banner danger" style={{ marginBottom: 14 }}>{error.message}</div>}
          {loading && !data && <div className="empty">불러오는 중…</div>}

          {importantFlags.length > 0 && (
            <div className="banner warn" style={{ marginBottom: 14 }}>
              <strong>데이터 확인 필요</strong>
              {importantFlags.slice(0, 3).map((f, i) => <span key={i}>· {flagText(f.code)}{flagDetail(f.code, f.detail) ? ` (${flagDetail(f.code, f.detail)})` : ''}</span>)}
            </div>
          )}

          {data && (
            <div className="stack" style={{ gap: 14 }}>
              <div className="grid grid-4">
                <Stat label="순자산" value={worth ? moneyShort(worth.net_worth) : '—'}
                  sub={worth ? (worth.complete ? `자산 ${moneyShort(worth.total_assets)} · 부채 ${moneyShort(worth.total_liabilities)}` : '일부 항목 제외됨') : '계좌를 등록하세요'} />
                <Stat label="유동 자산" value={worth ? moneyShort(worth.liquid_assets) : '—'}
                  sub={runwayMonths ? `월 지출 기준 약 ${runwayMonths}개월` : '월 지출 데이터 없음'} />
                <Stat label="월평균 지출" value={expense?.available ? moneyShort(expense.monthly_average) : '—'}
                  sub={expense?.available ? `최근 ${expense.months_considered}개월${expense.partial ? ' · 일부 달만 기록' : ''}` : '수입·지출을 기록하세요'} />
                <Stat label="투자 평가액" value={portfolio ? moneyShort(portfolio.computed.total_value_base) : '—'}
                  sub={portfolio?.holdings?.length ? `상위 3종목 ${portfolio.computed.top3_concentration_pct}%` : '보유 종목 없음'} />
              </div>

              <div className="grid grid-2">
                <section className="card">
                  <div className="card-head"><h2>다가오는 일정</h2><Link to="/data/calendar-events" className="small">관리</Link></div>
                  {conflicts.length > 0 && <div className="banner warn" style={{ margin: 12 }}>겹치는 일정 {conflicts.length}건이 있습니다</div>}
                  <ul className="list">
                    {[...interviews.map((i: any) => ({ t: i.starts_at, title: `${i.company} ${i.stage}`, tag: '면접' })),
                      ...events.map((e: any) => ({ t: e.starts_at, title: e.title, tag: enumLabel(e.kind) }))]
                      .sort((a, b) => a.t.localeCompare(b.t)).slice(0, 7)
                      .map((e, n) => (
                        <li key={n}><span className="faint" style={{ width: 120, flex: 'none' }}>{dateTime(e.t)}</span><span style={{ flex: 1 }}>{e.title}</span><span className="chip">{e.tag}</span></li>
                      ))}
                    {interviews.length + events.length === 0 && <li className="faint">예정된 일정이 없습니다</li>}
                  </ul>
                </section>

                <section className="card">
                  <div className="card-head"><h2>진행 중인 채용</h2><Link to="/data/job-applications" className="small">관리</Link></div>
                  <ul className="list">
                    {apps.slice(0, 7).map((a: any) => (
                      <li key={a.ref}><span style={{ flex: 1 }}><strong>{a.company}</strong> <span className="muted">{a.role}</span></span><span className="chip accent">{enumLabel(a.status)}</span></li>
                    ))}
                    {apps.length === 0 && <li className="faint">진행 중인 채용이 없습니다</li>}
                  </ul>
                </section>

                <section className="card">
                  <div className="card-head"><h2>목표</h2><Link to="/data/goals" className="small">관리</Link></div>
                  <ul className="list">
                    {goals.slice(0, 6).map((g: any) => (
                      <li key={g.ref} style={{ display: 'block' }}>
                        <div className="row"><span style={{ flex: 1 }}>{g.title}</span><span className="faint">{g.progress_pct ? `${g.progress_pct}%` : enumLabel(g.horizon)}{g.target_date && ` · ${dateOnly(g.target_date)}`}</span></div>
                        {g.progress_pct && <div className="bar" style={{ marginTop: 6 }}><span style={{ width: `${Math.min(100, Number(g.progress_pct))}%` }} /></div>}
                      </li>
                    ))}
                    {goals.length === 0 && <li className="faint">진행 중인 목표가 없습니다</li>}
                  </ul>
                </section>

                <section className="card">
                  <div className="card-head"><h2>할 일</h2><Link to="/data/tasks" className="small">관리</Link></div>
                  <ul className="list">
                    {tasks.slice(0, 7).map((t: any) => (
                      <li key={t.ref}><span style={{ flex: 1 }}>{t.title}</span>
                        {t.overdue && <span className="chip danger">지연</span>}
                        {t.priority === 'high' && <span className="chip warn">높음</span>}
                        <span className="faint">{t.due_on ? dateOnly(t.due_on) : ''}</span></li>
                    ))}
                    {tasks.length === 0 && <li className="faint">열린 할 일이 없습니다</li>}
                  </ul>
                </section>
              </div>

              <div className="grid grid-2">
                <section className="card">
                  <div className="card-head"><h2>계좌 · 부채</h2><Link to="/data/accounts" className="small">관리</Link></div>
                  <div className="table-wrap">
                    <table className="table">
                      <tbody>
                        {(accounts?.accounts ?? []).map((a: any) => (
                          <tr key={a.ref}><td>{a.name}<div className="faint">{a.institution ?? enumLabel(a.kind)}</div></td><td className="num">{money(a.balance, a.currency)}<div className="faint">{relative(a.as_of)}</div></td></tr>
                        ))}
                        {(accounts?.liabilities ?? []).map((l: any) => (
                          <tr key={l.ref}><td>{l.name}<div className="faint">부채 · {enumLabel(l.kind)}</div></td><td className="num" style={{ color: 'var(--danger)' }}>-{money(l.balance, l.currency)}</td></tr>
                        ))}
                        {!accounts?.accounts?.length && !accounts?.liabilities?.length && <tr><td className="faint">등록된 계좌가 없습니다</td></tr>}
                      </tbody>
                    </table>
                  </div>
                </section>
                <section className="card">
                  <div className="card-head"><h2>운동 (최근 4주)</h2><Link to="/data/workout-logs" className="small">관리</Link></div>
                  <div className="card-pad grid grid-3">
                    <Stat label="횟수" value={`${health?.sessions ?? 0}회`} />
                    <Stat label="총 시간" value={`${health?.total_minutes ?? 0}분`} />
                    <Stat label="마지막 운동" value={health?.last_session_on ? relative(health.last_session_on) : '—'} />
                  </div>
                </section>
              </div>
            </div>
          )}
        </div>

        <aside className="dash-side">
          <AdvisorChat
            compact
            conversationId={panelConversation}
            onConversationCreated={setPanelConversation}
            header={
              <div className="chat-head">
                <h2 style={{ flex: 1 }}>AI 어드바이저</h2>
                {panelConversation && (
                  <>
                    <button className="btn sm" onClick={() => navigate(`/advisor/${panelConversation}`)}>크게 보기</button>
                    <button className="btn sm ghost" onClick={() => setPanelConversation(null)}>새 상담</button>
                  </>
                )}
              </div>
            }
          />
        </aside>
      </div>
    </div>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="card card-pad">
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  );
}
