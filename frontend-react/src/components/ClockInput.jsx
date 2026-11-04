import { useState } from 'react';
import { msToClock, parseClock } from '../lib/format';

/**
 * Campo de tiempo mm:ss.s. Confirma con Enter o al salir; Esc descarta.
 * Para que refleje cambios externos, el padre lo monta con `key={valueMs}`.
 */
export default function ClockInput({ valueMs, onCommit, invalid = false, className = '', ...rest }) {
  const [text, setText] = useState(msToClock(valueMs));
  const [bad, setBad] = useState(false);

  const commit = () => {
    const ms = parseClock(text);
    if (ms === null) {
      setBad(true);
      return;
    }
    setBad(false);
    if (ms !== valueMs) onCommit(ms);
    else setText(msToClock(ms));
  };

  return (
    <input
      {...rest}
      value={text}
      inputMode="decimal"
      spellCheck={false}
      onChange={(e) => {
        setText(e.target.value);
        setBad(false);
      }}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          commit();
        } else if (e.key === 'Escape') {
          setText(msToClock(valueMs));
          setBad(false);
        }
      }}
      title={bad ? 'Formato: mm:ss.s (por ejemplo 01:23.4)' : rest.title}
      className={`w-24 bg-surface-highest rounded-lg py-1.5 px-2 text-xs font-mono text-center focus:outline-none focus:ring-1 ${
        bad || invalid ? 'ring-1 ring-error text-error focus:ring-error' : 'focus:ring-primary'
      } ${className}`}
    />
  );
}
