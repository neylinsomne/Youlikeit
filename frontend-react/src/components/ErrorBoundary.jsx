import { Component } from 'react';
import { Button, Icon } from './ui';

/** Evita que un error de render deje la pantalla en blanco. Se reinicia al cambiar de ruta (key). */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    console.error('[estudio] error de render', error, info?.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="max-w-xl mx-auto mt-16 text-center">
        <Icon name="sentiment_dissatisfied" className="text-4xl text-error" />
        <h2 className="font-headline text-xl font-black uppercase mt-3">Algo se rompió en esta página</h2>
        <p className="text-xs text-on-surface-variant mt-2 font-mono break-words">{String(this.state.error?.message ?? this.state.error)}</p>
        <Button className="mt-6" variant="accent" icon="refresh" onClick={() => this.setState({ error: null })}>
          Reintentar
        </Button>
      </div>
    );
  }
}
