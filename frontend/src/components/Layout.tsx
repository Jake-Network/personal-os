import { useEffect, useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { api } from '../api/client';
import type { Proposal, ProviderStatus } from '../api/types';
import { RESOURCES } from '../lib/resources';

export function Layout() {
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(0);
  const [provider, setProvider] = useState<ProviderStatus | null>(null);

  useEffect(() => {
    setOpen(false);
    api<Proposal[]>('/api/proposals?status=pending').then((p) => setPending(p.length)).catch(() => {});
    api<ProviderStatus>('/api/settings/ai-provider').then(setProvider).catch(() => {});
  }, [location.pathname]);

  const groups = [...new Set(RESOURCES.map((r) => r.group))];
  const providerDot = provider?.connected && provider.plan_usage_enabled ? 'on' : provider?.status === 'needs_reauth' ? 'off' : '';

  return (
    <div className="app">
      <div className="mobile-bar">
        <button className="btn sm" onClick={() => setOpen((v) => !v)} aria-label="메뉴">☰</button>
        Personal OS
      </div>
      <nav className={`sidebar${open ? ' open' : ''}`}>
        <div className="brand">
          Personal OS<small>나의 실제 상황을 아는 AI 상담</small>
        </div>
        <NavLink to="/" end className="nav-link">대시보드</NavLink>
        <NavLink to="/advisor" className="nav-link">AI 상담</NavLink>
        <NavLink to="/approvals" className="nav-link">
          승인 대기 {pending > 0 && <span className="chip warn">{pending}</span>}
        </NavLink>
        <NavLink to="/memory" className="nav-link">기억 · 의사결정</NavLink>

        <div className="nav-section">데이터</div>
        {groups.map((g) => (
          <div key={g}>
            {RESOURCES.filter((r) => r.group === g).map((r) => (
              <NavLink key={r.name} to={`/data/${r.name}`} className="nav-link">
                <span>{r.label}</span>
                <span className="faint">{g}</span>
              </NavLink>
            ))}
          </div>
        ))}

        <div className="nav-section">설정</div>
        <NavLink to="/settings/ai-provider" className="nav-link">
          <span>AI Provider</span>
          <span className={`dot ${providerDot}`} title={provider?.connected ? '연결됨' : '연결 안 됨'} />
        </NavLink>
        <NavLink to="/settings/privacy" className="nav-link">데이터 공유</NavLink>
      </nav>
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}
