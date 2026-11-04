import { Route, Routes } from 'react-router-dom';
import Layout from './components/Layout';
import Biblioteca from './pages/Biblioteca';
import Editor from './pages/Editor';
import Inicio from './pages/Inicio';
import Momentos from './pages/Momentos';
import NoEncontrado from './pages/NoEncontrado';
import Revision from './pages/Revision';
import Trabajos from './pages/Trabajos';
import Vocabulario from './pages/Vocabulario';

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Inicio />} />
        <Route path="biblioteca" element={<Biblioteca />} />
        <Route path="momentos" element={<Momentos />} />
        <Route path="editor" element={<Editor />} />
        <Route path="revision" element={<Revision />} />
        <Route path="trabajos" element={<Trabajos />} />
        <Route path="vocabulario" element={<Vocabulario />} />
        <Route path="*" element={<NoEncontrado />} />
      </Route>
    </Routes>
  );
}
