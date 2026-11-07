/** Clases compartidas de formularios (en un .js para no romper Fast Refresh). */
export const inputCls =
  'w-full bg-surface-highest border border-transparent rounded-lg py-2 px-3 text-sm text-on-surface ' +
  'placeholder:text-on-surface-variant/50 focus:border-primary/40 focus:outline-none focus:ring-1 ' +
  'focus:ring-primary disabled:opacity-50 disabled:cursor-not-allowed';

export const selectCls = `${inputCls} cursor-pointer`;

export const textareaCls = `${inputCls} resize-y min-h-[4.5rem]`;

export const labelCls = 'text-[10px] font-bold text-on-surface-variant uppercase tracking-widest block mb-1.5';

export const checkboxCls = 'h-3.5 w-3.5 accent-primary-glow cursor-pointer';
