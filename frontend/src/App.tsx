import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import Layout from '@/components/Layout';
import NewProject from '@/pages/NewProject';
import TaskProgress from '@/pages/TaskProgress';
import OutlineReview from '@/pages/OutlineReview';
import BidWorkbench from '@/pages/BidWorkbench';
import KnowledgeBase from '@/pages/KnowledgeBase';
import Projects from '@/pages/Projects';
import Companies from '@/pages/Companies';
const App: React.FC = () => {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Navigate to="/new" replace />} />
        <Route path="/new" element={<NewProject />} />
        <Route path="/progress/:projectId" element={<TaskProgress />} />
        <Route path="/outline/:projectId" element={<OutlineReview />} />
        <Route path="/workbench/:projectId" element={<BidWorkbench />} />
        <Route path="/knowledge" element={<KnowledgeBase />} />
        <Route path="/companies" element={<Companies />} />
        <Route path="/projects" element={<Projects />} />
        <Route path="*" element={<Navigate to="/new" replace />} />
      </Routes>
    </Layout>
  );
};
export default App;
