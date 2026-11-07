export const NAV_ITEMS = [
  { path: '/', icon: 'home', label: 'Inicio', title: 'Inicio' },
  { path: '/biblioteca', icon: 'video_library', label: 'Biblioteca', title: 'Biblioteca de películas' },
  { path: '/momentos', icon: 'movie_filter', label: 'Momentos', title: 'Momentos clave' },
  { path: '/editor', icon: 'movie_edit', label: 'Editor', title: 'Editor de lecciones' },
  { path: '/revision', icon: 'rate_review', label: 'Revisión', title: 'Revisión y publicación' },
  { path: '/trabajos', icon: 'pending_actions', label: 'Trabajos', title: 'Trabajos en cola' },
  { path: '/vocabulario', icon: 'menu_book', label: 'Vocabulario', title: 'Vocabulario' },
];

export function titleFor(pathname) {
  const match = NAV_ITEMS.find((n) => (n.path === '/' ? pathname === '/' : pathname.startsWith(n.path)));
  return match?.title ?? 'Página no encontrada';
}
