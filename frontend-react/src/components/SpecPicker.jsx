import { DIMENSIONS } from '../lib/labels';
import { selectCls } from '../lib/styles';

/**
 * Selector "dimensión : valor" contra el vocabulario controlado.
 * `vocab` es el resultado de useVocab(); onChange({ dimension, value }).
 */
export default function SpecPicker({
  vocab,
  dimension,
  value,
  onChange,
  allowAnyDimension = false,
  dimensions = DIMENSIONS,
  idPrefix = 'spec',
  required = false,
}) {
  const options = dimension ? vocab.options(dimension) : [];
  return (
    <div className="grid grid-cols-2 gap-2">
      <select
        id={`${idPrefix}-dim`}
        aria-label="Dimensión"
        className={selectCls}
        value={dimension || ''}
        onChange={(e) => onChange({ dimension: e.target.value, value: '' })}
      >
        {allowAnyDimension && <option value="">Cualquier dimensión</option>}
        {dimensions.map((d) => (
          <option key={d.id} value={d.id}>
            {d.label}
          </option>
        ))}
      </select>
      <select
        id={`${idPrefix}-val`}
        aria-label="Valor"
        className={selectCls}
        value={value || ''}
        required={required}
        disabled={!dimension || vocab.loading}
        onChange={(e) => onChange({ dimension, value: e.target.value })}
      >
        <option value="">{vocab.loading ? 'Cargando…' : dimension ? 'Elige…' : '—'}</option>
        {options.map((o) => (
          <option key={o.id} value={o.id}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}
