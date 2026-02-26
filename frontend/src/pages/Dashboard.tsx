import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { clsx } from 'clsx'
import { api } from '../lib/api'
import PickCard from '../components/PickCard'

const CURRENT_SEASON = 2025
const CURRENT_WEEK = 1

export default function Dashboard() {
  const qc = useQueryClient()
  const [season] = useState(CURRENT_SEASON)
  const [week] = useState(CURRENT_WEEK)
  const [newEntryName, setNewEntryName] = useState('')
  const [overrides, setOverrides] = useState<Record<number, string>>({})  // entryId → team
  const [updateMsg, setUpdateMsg] = useState('')

  const { data: entries, isLoading: entriesLoading } = useQuery({
    queryKey: ['entries', season],
    queryFn: () => api.getEntries(season),
  })

  const { data: recData, isLoading: recLoading } = useQuery({
    queryKey: ['recommendations', week, season],
    queryFn: () => api.getRecommendations(week, season),
    enabled: (entries?.length ?? 0) > 0,
  })

  const createEntry = useMutation({
    mutationFn: () => api.createEntry(newEntryName.trim(), season),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['entries', season] })
      setNewEntryName('')
    },
  })

  const submitPick = useMutation({
    mutationFn: ({ entryId, team }: { entryId: number; team: string }) =>
      api.submitPick(entryId, team, season, week),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['entries', season] })
      qc.invalidateQueries({ queryKey: ['recommendations', week, season] })
    },
  })

  const updateResults = useMutation({
    mutationFn: () => api.updateResults(season, week - 1),
    onSuccess: (data) => {
      setUpdateMsg(data.message)
      qc.invalidateQueries()
      setTimeout(() => setUpdateMsg(''), 4000)
    },
  })

  const aliveEntries = entries?.filter(e => e.is_alive) ?? []
  const deadEntries = entries?.filter(e => !e.is_alive) ?? []

  return (
    <div className="max-w-7xl mx-auto px-4 py-6 space-y-6">

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Season {season} — Week {week}</h1>
          <p className="text-slate-400 text-sm mt-0.5">
            {aliveEntries.length} alive · {deadEntries.length} eliminated
          </p>
        </div>
        <div className="flex gap-2 items-center">
          {updateMsg && (
            <span className="text-xs text-accent-green">{updateMsg}</span>
          )}
          <button
            onClick={() => updateResults.mutate()}
            disabled={updateResults.isPending}
            className="btn-ghost text-sm"
          >
            {updateResults.isPending ? 'Refreshing…' : 'Refresh Results'}
          </button>
        </div>
      </div>

      {/* Add entry */}
      <div className="card flex gap-2 items-center">
        <input
          value={newEntryName}
          onChange={e => setNewEntryName(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && newEntryName.trim() && createEntry.mutate()}
          placeholder="New entry name…"
          className="flex-1 bg-surface-elevated border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-accent-blue"
        />
        <button
          onClick={() => createEntry.mutate()}
          disabled={!newEntryName.trim() || createEntry.isPending}
          className="btn-primary text-sm"
        >
          Add Entry
        </button>
      </div>

      {/* This week's picks */}
      {entriesLoading || recLoading ? (
        <div className="text-slate-500 text-sm py-8 text-center">Loading recommendations…</div>
      ) : aliveEntries.length === 0 ? (
        <div className="card text-center py-12 text-slate-500">
          Add an entry above to get started.
        </div>
      ) : (
        <div className="space-y-4">
          <h2 className="text-lg font-semibold">This Week's Picks</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
            {aliveEntries.map(entry => {
              const rec = recData?.recommendations.find(r => r.entry_id === entry.id)
              const override = overrides[entry.id]
              const effectiveTeam = override ?? rec?.recommended_team

              // Build candidate picks for this entry
              // Show top 4 available teams for easy override
              const usedTeams = new Set(entry.used_teams)

              return (
                <div key={entry.id} className="card space-y-3">
                  {/* Entry header */}
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <div className="w-2 h-2 rounded-full bg-accent-green" />
                      <span className="font-semibold">{entry.name}</span>
                    </div>
                    <span className="text-xs text-slate-400">
                      {entry.used_teams.length} teams used
                    </span>
                  </div>

                  {/* Recommended pick */}
                  {rec ? (
                    <>
                      <PickCard
                        team={effectiveTeam ?? rec.recommended_team}
                        opponent={null}
                        isHome={true}
                        winProb={rec.win_prob ?? 0}
                        survivalProb={rec.survival_prob}
                        isRecommended={!override}
                        isSelected={true}
                        onClick={() => {
                          const newOverride = { ...overrides }
                          delete newOverride[entry.id]
                          setOverrides(newOverride)
                        }}
                      />
                      <div className="flex gap-2 items-center">
                        <button
                          onClick={() => submitPick.mutate({ entryId: entry.id, team: effectiveTeam! })}
                          disabled={!effectiveTeam || submitPick.isPending}
                          className="btn-primary text-xs flex-1"
                        >
                          Lock in {effectiveTeam}
                        </button>
                        <span className="text-xs text-slate-500">
                          Survival: {Math.round(rec.survival_prob * 100)}%
                        </span>
                      </div>

                      {/* Future picks preview */}
                      {Object.keys(rec.strategy_picks).length > 0 && (
                        <div className="mt-1">
                          <p className="text-[10px] text-slate-500 mb-1">Season strategy:</p>
                          <div className="flex flex-wrap gap-1">
                            {Object.entries(rec.strategy_picks).slice(0, 6).map(([w, t]) => (
                              <span key={w} className="text-[10px] bg-slate-700/50 rounded px-1.5 py-0.5 text-slate-300">
                                W{w}: {t}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                    </>
                  ) : (
                    <div className="text-sm text-slate-500 py-4 text-center">
                      No recommendation available
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* Eliminated entries */}
      {deadEntries.length > 0 && (
        <div className="space-y-2">
          <h2 className="text-base font-medium text-slate-400">Eliminated</h2>
          <div className="flex flex-wrap gap-2">
            {deadEntries.map(e => (
              <div key={e.id} className="card-elevated opacity-60 px-3 py-2 flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-accent-red" />
                <span className="text-sm">{e.name}</span>
                <span className="text-xs text-slate-500">Wk {e.eliminated_week}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
