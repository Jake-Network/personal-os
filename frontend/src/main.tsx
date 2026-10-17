import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { createBrowserRouter, RouterProvider } from 'react-router-dom';
import { Layout } from './components/Layout';
import { AIProviderPage } from './pages/AIProviderPage';
import { AdvisorPage } from './pages/AdvisorPage';
import { ApprovalsPage } from './pages/ApprovalsPage';
import { DashboardPage } from './pages/DashboardPage';
import { DataPage } from './pages/DataPage';
import { MemoryPage } from './pages/MemoryPage';
import { PrivacyPage } from './pages/PrivacyPage';
import './styles.css';

const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: '/', element: <DashboardPage /> },
      // One route so the page (and a live answer stream) survives /advisor → /advisor/:id.
      { path: '/advisor/:id?', element: <AdvisorPage /> },
      { path: '/approvals', element: <ApprovalsPage /> },
      { path: '/memory', element: <MemoryPage /> },
      { path: '/data/:resource', element: <DataPage /> },
      { path: '/settings/ai-provider', element: <AIProviderPage /> },
      { path: '/settings/privacy', element: <PrivacyPage /> },
      { path: '*', element: <div className="page"><div className="empty">페이지를 찾을 수 없습니다.</div></div> },
    ],
  },
]);

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
);
