// src/App.tsx
import type { ReactElement } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import { useWorkflow } from './store/workflow'
import ConnectPage from './pages/ConnectPage'
import SchemaPage from './pages/SchemaPage'
import ModePage from './pages/ModePage'
import GeneratePage from './pages/GeneratePage'
import PreviewPage from './pages/PreviewPage'
import OutputPage from './pages/OutputPage'
import ResultPage from './pages/ResultPage'
import HowItWorksPage from './pages/HowItWorksPage'

function Guard({ need, to, children }: { need: 'schema' | 'config' | 'job'; to: string; children: ReactElement }) {
  const wf = useWorkflow()
  const ok = need === 'schema' ? wf.schema : need === 'config' ? wf.config : wf.jobId
  return ok ? children : <Navigate to={to} replace />
}

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/connect" replace />} />
        <Route path="/connect" element={<ConnectPage />} />
        <Route path="/schema" element={<Guard need="schema" to="/connect"><SchemaPage /></Guard>} />
        <Route path="/mode" element={<Guard need="schema" to="/connect"><ModePage /></Guard>} />
        <Route path="/generate" element={<Guard need="config" to="/mode"><GeneratePage /></Guard>} />
        <Route path="/preview" element={<Guard need="job" to="/mode"><PreviewPage /></Guard>} />
        <Route path="/output" element={<Guard need="job" to="/mode"><OutputPage /></Guard>} />
        <Route path="/result" element={<Guard need="job" to="/mode"><ResultPage /></Guard>} />
        <Route path="/how-it-works" element={<HowItWorksPage />} />
        <Route path="*" element={<Navigate to="/connect" replace />} />
      </Route>
    </Routes>
  )
}
