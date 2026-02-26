import { BrowserRouter, Routes, Route } from 'react-router-dom'
import Nav from './components/Nav'
import Dashboard from './pages/Dashboard'
import Schedule from './pages/Schedule'
import Simulation from './pages/Simulation'

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-surface">
        <Nav />
        <main>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/schedule" element={<Schedule />} />
            <Route path="/simulation" element={<Simulation />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}
