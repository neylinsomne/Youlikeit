import Sidebar from './Sidebar';
import Header from './Header';

export default function Layout({ children, title }) {
  return (
    <div className="min-h-screen">
      <Sidebar />
      <Header title={title} />
      <main className="pt-20 pl-72 pr-8 pb-12 min-h-screen">
        {children}
      </main>
    </div>
  );
}
