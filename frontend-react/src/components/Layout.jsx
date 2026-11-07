import { Outlet, useLocation } from 'react-router-dom';
import ErrorBoundary from './ErrorBoundary';
import Header from './Header';
import Sidebar from './Sidebar';
import ToastProvider from './ToastProvider';

export default function Layout() {
  const { pathname } = useLocation();
  return (
    <ToastProvider>
      <div className="min-h-screen">
        <Sidebar />
        <Header />
        <main className="pt-20 pl-72 pr-8 pb-12 min-h-screen">
          <ErrorBoundary key={pathname}>
            <Outlet />
          </ErrorBoundary>
        </main>
      </div>
    </ToastProvider>
  );
}
