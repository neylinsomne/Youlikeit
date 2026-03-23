import { Routes, Route } from 'react-router-dom';
import Pipeline from './pages/Pipeline';
import Analytics from './pages/Analytics';
import ShortsEditor from './pages/ShortsEditor';
import ContentBank from './pages/ContentBank';
import KnowledgeBase from './pages/KnowledgeBase';
import ReviewQueue from './pages/ReviewQueue';
import Planner from './pages/Planner';
import Export from './pages/Export';

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Pipeline />} />
      <Route path="/analytics" element={<Analytics />} />
      <Route path="/shorts" element={<ShortsEditor />} />
      <Route path="/content" element={<ContentBank />} />
      <Route path="/review" element={<ReviewQueue />} />
      <Route path="/planner" element={<Planner />} />
      <Route path="/knowledge" element={<KnowledgeBase />} />
      <Route path="/export" element={<Export />} />
    </Routes>
  );
}
