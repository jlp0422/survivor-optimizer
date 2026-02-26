import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, Legend,
} from 'recharts'
import type { SimulationResponse } from '../lib/api'

interface SurvivalCurveProps {
  simulations: SimulationResponse[]    // one per entry
  entryNames: string[]
  currentWeek: number
}

const COLORS = ['#3b82f6', '#22c55e', '#eab308', '#ef4444', '#a855f7', '#06b6d4']

interface DataPoint {
  week: number
  [entryName: string]: number
}

export default function SurvivalCurve({ simulations, entryNames, currentWeek }: SurvivalCurveProps) {
  if (simulations.length === 0) {
    return (
      <div className="flex items-center justify-center h-48 text-slate-500 text-sm">
        Run a simulation to see survival curves
      </div>
    )
  }

  // Build data: for each week, survival prob = win prob * (implied chain)
  // We approximate: survival curve = cumulative product of weekly best picks
  const allWeeks = Array.from(
    new Set(simulations.flatMap(s => s.team_survival_probs.map(() => s.week)))
  ).sort((a, b) => a - b)

  // For each simulation (entry), compute the survival probability per week
  // survival_prob in the response is the full-season survival, not per-week
  // We'll plot each entry's top pick win prob per simulated week as a proxy
  const data: DataPoint[] = simulations[0]?.team_survival_probs
    .slice(0, 12)  // top 12 teams
    .map((tp, i) => {
      const point: DataPoint = { week: currentWeek + i }
      simulations.forEach((sim, si) => {
        const name = entryNames[si] ?? `Entry ${si + 1}`
        // Approximate survival: multiply survival probs greedily
        const sortedProbs = sim.team_survival_probs
          .slice(0, i + 1)
          .map(t => t.survival_prob)
        point[name] = sortedProbs.length > 0
          ? sortedProbs[sortedProbs.length - 1]
          : 0
      })
      return point
    }) ?? []

  // Simpler: just plot survival probs for the first simulation's teams
  const survivalData = simulations.map((sim, si) => {
    const name = entryNames[si] ?? `Entry ${si + 1}`
    return { name, data: sim.team_survival_probs }
  })

  // Build week-indexed chart data
  const chartData: DataPoint[] = []
  const topProbs = simulations[0]?.team_survival_probs ?? []
  topProbs.forEach((_, i) => {
    const point: DataPoint = { week: currentWeek + i }
    survivalData.forEach(({ name, data: sdata }) => {
      if (sdata[i]) point[name] = Math.round(sdata[i].survival_prob * 100)
    })
    chartData.push(point)
  })

  return (
    <div>
      <h3 className="text-sm font-medium text-slate-300 mb-3">
        Simulated Survival Probability — Week {currentWeek} onwards
      </h3>
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={chartData} margin={{ top: 5, right: 20, left: 0, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
          <XAxis
            dataKey="week"
            stroke="#64748b"
            tick={{ fill: '#94a3b8', fontSize: 11 }}
            label={{ value: 'Week', position: 'insideBottom', offset: -2, fill: '#64748b', fontSize: 11 }}
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
            labelStyle={{ color: '#94a3b8' }}
            formatter={(val: number) => [`${val}%`, '']}
          />
          <Legend
            wrapperStyle={{ fontSize: 12, color: '#94a3b8', paddingTop: 8 }}
          />
          <ReferenceLine x={currentWeek} stroke="#3b82f6" strokeDasharray="4 2" opacity={0.5} />
          {survivalData.map(({ name }, i) => (
            <Line
              key={name}
              type="monotone"
              dataKey={name}
              stroke={COLORS[i % COLORS.length]}
              strokeWidth={2}
              dot={{ r: 3, fill: COLORS[i % COLORS.length] }}
              activeDot={{ r: 5 }}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
