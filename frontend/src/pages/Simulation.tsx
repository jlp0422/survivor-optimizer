import { useState } from 'react'
import { useQuery, useMutation } from '@tanstack/react-query'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell,
} from 'recharts'
import { api, SimulationResponse } from '../lib/api'
import SurvivalCurve from '../components/SurvivalCurve'

const CURRENT_SEASON = 2025
const CURRENT_WEEK = 1

export default function Simulation() {
  const [season] = useState(CURRENT_SEASON)
  const [week, setWeek] = useState(CURRENT_WEEK)
  const [nSims, setNSims] = useState(50000)
  const [selectedEntry, setSelectedEntry] = useState<number | undefined>()
  const [simResults, setSimResults] = useState<SimulationResponse[]>([])

  const { data: entries } = useQuery({
    queryKey: ['entries', season],
    queryFn: () => api.getEntries(season),
  })

  const runSim = useMutation({
    mutationFn: () => api.runSimulation(week, season, selectedEntry, nSims),
    onSuccess: (data) => {
      setSimResults(prev => {
        // Replace or append
        const filtered = prev.filter(s => s.season !== season || s.week !== week)
        return [...filtered, data]
      })
    },
  })

  const aliveEntries = entries?.filter(e => e.is_alive) ?? []
  const latestSim = simResults.find(s => s.season === season && s.week === week)

  const barData = latestSim?.team_survival_probs
    .slice(0, 20)
    .map(t => ({
      team: t.team,
      winProb: Math.round(t.win_prob * 100),
      survivalProb: Math.round(t.survival_prob * 100),
      opponent: t.opponent,
      isHome: t.is_home,
    })) ?? []

  const scarcityData = latestSim
    ? Object.entries(latestSim.scarcity_by_week)
        .map(([w, n]) => ({ week: `W${w}`, count: n }))
        .sort((a, b) => parseInt(a.week.slice(1)) - parseInt(b.week.slice(1)))
    : []

  return (
    <div className="max-w-7xl mx-auto px-4 py-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Simulation</h1>
        <p className="text-slate-400 text-sm mt-0.5">
          Monte Carlo survival analysis · {nSims.toLocaleString()} simulations
        </p>
      </div>

      {/* Controls */}
      <div className="card flex flex-wrap gap-4 items-end">
        <div>
          <label className="text-xs text-slate-400 block mb-1">Week</label>
          <input
            type="number"
            value={week}
            min={1} max={18}
            onChange={e => setWeek(parseInt(e.target.value))}
            className="w-20 bg-surface-elevated border border-slate-600 rounded-lg px-2 py-1.5 text-sm text-slate-100 focus:outline-none focus:border-accent-blue"
          />
        </div>
        <div>
          <label className="text-xs text-slate-400 block mb-1">Simulations</label>
          <select
            value={nSims}
            onChange={e => setNSims(parseInt(e.target.value))}
            className="bg-surface-elevated border border-slate-600 rounded-lg px-2 py-1.5 text-sm text-slate-100 focus:outline-none focus:border-accent-blue"
          >
            <option value={10000}>10,000</option>
            <option value={50000}>50,000</option>
            <option value={100000}>100,000</option>
          </select>
        </div>
        <div>
          <label className="text-xs text-slate-400 block mb-1">Entry (optional)</label>
          <select
            value={selectedEntry ?? ''}
            onChange={e => setSelectedEntry(e.target.value ? parseInt(e.target.value) : undefined)}
            className="bg-surface-elevated border border-slate-600 rounded-lg px-2 py-1.5 text-sm text-slate-100 focus:outline-none focus:border-accent-blue"
          >
            <option value="">All teams</option>
            {aliveEntries.map(e => (
              <option key={e.id} value={e.id}>{e.name}</option>
            ))}
          </select>
        </div>
        <button
          onClick={() => runSim.mutate()}
          disabled={runSim.isPending}
          className="btn-primary"
        >
          {runSim.isPending ? 'Running…' : 'Run Simulation'}
        </button>
        {runSim.isError && (
          <span className="text-xs text-accent-red">{(runSim.error as Error).message}</span>
        )}
      </div>

      {latestSim ? (
        <div className="space-y-6">
          {/* Summary */}
          <div className="grid grid-cols-3 gap-4">
            <div className="card text-center">
              <div className="text-2xl font-bold text-accent-green">
                {latestSim.team_survival_probs[0]
                  ? Math.round(latestSim.team_survival_probs[0].survival_prob * 100)
                  : '—'}%
              </div>
              <div className="text-xs text-slate-400 mt-1">Best survival prob</div>
              <div className="text-sm text-slate-300 mt-0.5">
                {latestSim.team_survival_probs[0]?.team}
              </div>
            </div>
            <div className="card text-center">
              <div className="text-2xl font-bold text-accent-blue">
                {latestSim.team_survival_probs.filter(t => t.win_prob >= 0.65).length}
              </div>
              <div className="text-xs text-slate-400 mt-1">Strong picks (≥65%)</div>
            </div>
            <div className="card text-center">
              <div className="text-2xl font-bold text-accent-yellow">
                {latestSim.n_simulations.toLocaleString()}
              </div>
              <div className="text-xs text-slate-400 mt-1">Simulations run</div>
            </div>
          </div>

          {/* Team survival bar chart */}
          <div className="card">
            <h2 className="text-sm font-semibold text-slate-300 mb-4">
              Team Survival Probabilities — Week {week}
            </h2>
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={barData} margin={{ top: 5, right: 20, left: 0, bottom: 30 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis
                  dataKey="team"
                  stroke="#64748b"
                  tick={{ fill: '#94a3b8', fontSize: 10 }}
                  angle={-45}
                  textAnchor="end"
                />
                <YAxis
                  stroke="#64748b"
                  tick={{ fill: '#94a3b8', fontSize: 11 }}
                  tickFormatter={(v) => `${v}%`}
                  domain={[0, 100]}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: '#1a1d27',
                    border: '1px solid #334155',
                    borderRadius: 8,
                    fontSize: 12,
                  }}
                  formatter={(val: number, name: string) => [
                    `${val}%`,
                    name === 'survivalProb' ? 'Survival' : 'Win Prob',
                  ]}
                />
                <Bar dataKey="survivalProb" name="survivalProb" radius={[4, 4, 0, 0]}>
                  {barData.map((entry, i) => (
                    <Cell
                      key={i}
                      fill={
                        entry.winProb >= 70 ? '#22c55e' :
                        entry.winProb >= 60 ? '#eab308' :
                        entry.winProb >= 50 ? '#f97316' : '#ef4444'
                      }
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* Survival curve */}
          <div className="card">
            <SurvivalCurve
              simulations={[latestSim]}
              entryNames={
                selectedEntry
                  ? [entries?.find(e => e.id === selectedEntry)?.name ?? 'Entry 1']
                  : ['All Teams']
              }
              currentWeek={week}
            />
          </div>

          {/* Scarcity analysis */}
          {scarcityData.length > 0 && (
            <div className="card">
              <h2 className="text-sm font-semibold text-slate-300 mb-1">
                Scarcity Analysis
              </h2>
              <p className="text-xs text-slate-500 mb-4">
                Strong teams (≥65% win prob) available per future week
              </p>
              <ResponsiveContainer width="100%" height={160}>
                <BarChart data={scarcityData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis dataKey="week" stroke="#64748b" tick={{ fill: '#94a3b8', fontSize: 11 }} />
                  <YAxis stroke="#64748b" tick={{ fill: '#94a3b8', fontSize: 11 }} allowDecimals={false} />
                  <Tooltip
                    contentStyle={{
                      backgroundColor: '#1a1d27',
                      border: '1px solid #334155',
                      borderRadius: 8,
                      fontSize: 12,
                    }}
                  />
                  <Bar dataKey="count" name="Strong teams" fill="#3b82f6" radius={[4, 4, 0, 0]}>
                    {scarcityData.map((entry, i) => (
                      <Cell
                        key={i}
                        fill={entry.count <= 2 ? '#ef4444' : entry.count <= 4 ? '#eab308' : '#22c55e'}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* Full table */}
          <div className="card overflow-x-auto">
            <h2 className="text-sm font-semibold text-slate-300 mb-3">Full Results Table</h2>
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-slate-400 border-b border-slate-700">
                  <th className="pb-2 pr-4">Team</th>
                  <th className="pb-2 pr-4">Matchup</th>
                  <th className="pb-2 pr-4">Win Prob</th>
                  <th className="pb-2">Survival Prob</th>
                </tr>
              </thead>
              <tbody>
                {latestSim.team_survival_probs.map(t => (
                  <tr key={t.team} className="border-b border-slate-800/50 hover:bg-slate-800/20">
                    <td className="py-2 pr-4 font-bold text-slate-200">{t.team}</td>
                    <td className="py-2 pr-4 text-slate-400 text-xs">
                      {t.is_home ? 'vs' : '@'} {t.opponent ?? '—'}
                    </td>
                    <td className="py-2 pr-4">
                      <div className="flex items-center gap-2">
                        <div className="w-16 h-1.5 bg-slate-700 rounded-full overflow-hidden">
                          <div
                            className={`h-full rounded-full ${
                              t.win_prob >= 0.70 ? 'bg-accent-green' :
                              t.win_prob >= 0.60 ? 'bg-yellow-500' :
                              t.win_prob >= 0.50 ? 'bg-orange-500' : 'bg-red-500'
                            }`}
                            style={{ width: `${t.win_prob * 100}%` }}
                          />
                        </div>
                        <span className={`text-xs font-medium ${
                          t.win_prob >= 0.70 ? 'text-accent-green' :
                          t.win_prob >= 0.60 ? 'text-yellow-400' :
                          t.win_prob >= 0.50 ? 'text-orange-400' : 'text-red-400'
                        }`}>
                          {Math.round(t.win_prob * 100)}%
                        </span>
                      </div>
                    </td>
                    <td className="py-2">
                      <span className="text-slate-200 font-medium">
                        {Math.round(t.survival_prob * 100)}%
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <div className="card text-center py-16 text-slate-500">
          Configure parameters above and click <strong className="text-slate-300">Run Simulation</strong>.
        </div>
      )}
    </div>
  )
}
