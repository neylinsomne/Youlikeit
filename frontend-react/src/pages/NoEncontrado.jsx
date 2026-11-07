import { Link, useLocation } from 'react-router-dom';
import { Icon } from '../components/ui';

export default function NoEncontrado() {
  const { pathname } = useLocation();
  return (
    <div className="max-w-lg mx-auto mt-20 text-center">
      <Icon name="explore_off" className="text-5xl text-outline" />
      <h2 className="font-headline text-3xl font-black uppercase tracking-tighter mt-4">Página no encontrada</h2>
      <p className="text-sm text-on-surface-variant mt-2">
        No existe <code className="font-mono text-on-surface">{pathname}</code> en el estudio.
      </p>
      <Link
        to="/"
        className="font-headline inline-flex items-center gap-1.5 mt-6 px-5 py-2.5 rounded-lg bg-primary-glow/10 text-primary-glow hover:bg-primary-glow/20 text-xs font-bold uppercase tracking-widest"
      >
        <Icon name="home" className="text-sm" />
        Volver al inicio
      </Link>
    </div>
  );
}
