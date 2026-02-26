import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../lib/api'
import TeamCalendar from '../components/TeamCalendar'

const CURRENT_SEASON = 2025
const CURRENT_WEEK = 1

export default function Schedule() {
  const [season] = useState(CURRENT_SEASON)
  const [selectedTeam, setSelectedTeam] = useState<string | null>(null)

  const { data: schedule, isLoading: schedLoading } = useQuery({
    queryKey: ['schedule', season],
    queryFn: () => api.getSchedule(season),
  })

  const { data: entries } = useQuery({
    queryKey: ['entries', season],
    queryFn: () => api.getEntries(season),
  })

  const { data: teamSchedule, isLoading: teamLoading } = useQuery({
    queryKey: ['teamSchedule', selectedTeam, season],
    queryFn: () => api.getTeamSchedule(selectedTeam!, season),
    enabled: !!selectedTeam,
  })

  return (
    <div className="max-w-7xl mx-auto px-4 py-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Season Calendar</h1>
        <p className="text-slate-400 text-sm mt-0.5">
          All 32 teams × remaining weeks. Click a team for detailed schedule.
        </p>
      </div>

      {/* Calendar grid */}
      <div className="card">
        {schedLoading ? (
          <div className="text-slate-500 text-sm py-12 text-center">Loading schedule…</div>
        ) : schedule ? (
          <TeamCalendar
            games={schedule.weeks}
            entries={entries ?? []}
            season={season}
            currentWeek={CURRENT_WEEK}
          />
        ) : (
          <div className="text-slate-500 text-sm py-12 text-center">
            No schedule data. Run the backfill script first.
          </div>
        )}
      </div>

      {/* Team detail panel */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="card md:col-span-1 space-y-1">
          <h2 className="text-sm font-semibold text-slate-300 mb-2">Team Detail</h2>
          <div className="grid grid-cols-4 gap-1">
            {['ARI','ATL','BAL','BUF','CAR','CHI','CIN','CLE',
              'DAL','DEN','DET','GB', 'HOU','IND','JAX','KC',
              'LAC','LAR','LV', 'MIA','MIN','NE', 'NO', 'NYG',
              'NYJ','PHI','PIT','SEA','SF', 'TB', 'TEN','WAS'].map(t => (
              <button
                key={t}
                onClick={() => setSelectedTeam(t === selectedTeam ? null : t)}
                className={`text-xs py-1 rounded transition-colors ${
                  t === selectedTeam
                    ? 'bg-accent-blue text-white'
                    : 'bg-slate-700/50 text-slate-300 hover:bg-slate-600/50'
                }`}
              >
                {t}
              </button>
            ))}
          </div>
        </div>

        {selectedTeam && (
          <div className="card md:col-span-2 space-y-2">
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-semibold text-slate-300">
                {selectedTeam} — {season} Schedule
              </h2>
              {teamSchedule?.used_by_entries.length ? (
                <span className="text-xs text-accent-yellow bg-yellow-500/10 px-2 py-0.5 rounded-full">
                  Used by {teamSchedule.used_by_entries.length} entr{teamSchedule.used_by_entries.length === 1 ? 'y' : 'ies'}
                </span>
              ) : null}
            </div>

            {teamLoading ? (
              <div className="text-slate-500 text-sm py-6 text-center">Loading…</div>
            ) : teamSchedule ? (
              <div className="space-y-1">
                {teamSchedule.games.map(game => (
                  <div
                    key={game.week}
                    className={`flex items-center justify-between py-1.5 px-2 rounded text-sm ${
                      game.week === CURRENT_WEEK ? 'bg-accent-blue/10 border border-accent-blue/30' : ''
                    }`}
                  >
                    <span className="text-slate-400 w-8">W{game.week}</span>
                    <span className="flex-1 text-slate-200">
                      {game.is_home ? 'vs' : '@'}{' '}
                      <span className="font-medium">{game.opponent}</span>
                    </span>
                    {game.is_played ? (
                      <span className={`text-xs font-bold ${game.result === 'W' ? 'text-accent-green' : 'text-accent-red'}`}>
                        {game.result}
                      </span>
                    ) : game.win_prob !== null ? (
                      <span className={`text-xs font-medium ${
                        game.win_prob >= 0.70 ? 'text-accent-green' :
                        game.win_prob >= 0.55 ? 'text-yellow-400' : 'text-slate-400'
                      }`}>
                        {Math.round(game.win_prob * 100)}%
                      </span>
                    ) : (
                      <span className="text-xs text-slate-600">—</span>
                    )}
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        )}
      </div>
    </div>
  )
}
