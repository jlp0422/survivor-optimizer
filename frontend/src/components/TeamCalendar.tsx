import { clsx } from 'clsx'
import type { Game, Entry } from '../lib/api'

interface TeamCalendarProps {
  games: Record<number, Game[]>   // week → games
  entries: Entry[]
  season: number
  currentWeek: number
}

const ALL_TEAMS = [
  'ARI','ATL','BAL','BUF','CAR','CHI','CIN','CLE',
  'DAL','DEN','DET','GB', 'HOU','IND','JAX','KC',
  'LAC','LAR','LV', 'MIA','MIN','NE', 'NO', 'NYG',
  'NYJ','PHI','PIT','SEA','SF', 'TB', 'TEN','WAS',
]

function getCellState(
  team: string,
  week: number,
  games: Record<number, Game[]>,
  entries: Entry[],
  currentWeek: number,
): 'used' | 'recommended' | 'strong' | 'available' | 'bye' | 'played' {
  // Check if any entry used this team
  const usedByAny = entries.some(e => e.used_teams.includes(team))
  if (usedByAny) return 'used'

  const weekGames = games[week] ?? []
  const game = weekGames.find(g => g.home_team === team || g.away_team === team)

  if (!game) return 'bye'

  if (game.home_win !== null) return 'played'

  if (week < currentWeek) return 'played'

  const prob = game.home_team === team ? game.home_win_prob : game.away_win_prob
  if (prob === null) return 'available'
  if (prob >= 0.70) return 'strong'
  return 'available'
}

function getWinProb(
  team: string,
  week: number,
  games: Record<number, Game[]>,
): number | null {
  const weekGames = games[week] ?? []
  const game = weekGames.find(g => g.home_team === team || g.away_team === team)
  if (!game) return null
  return game.home_team === team ? game.home_win_prob : game.away_win_prob
}

const STATE_CLASSES: Record<string, string> = {
  used:        'bg-slate-600/30 text-slate-500 cursor-default',
  recommended: 'bg-accent-green/25 text-accent-green border border-accent-green/50 font-bold',
  strong:      'bg-yellow-500/15 text-yellow-300 border border-yellow-500/30',
  available:   'bg-slate-700/30 text-slate-300 hover:bg-slate-600/40',
  bye:         'bg-transparent text-slate-700 cursor-default',
  played:      'bg-slate-800/30 text-slate-600 cursor-default',
}

const STATE_LABELS: Record<string, string> = {
  used:        'Used',
  recommended: '★ Top',
  strong:      'Strong',
  available:   'Avail',
  bye:         '—',
  played:      'Done',
}

export default function TeamCalendar({
  games,
  entries,
  currentWeek,
}: TeamCalendarProps) {
  const weeks = Object.keys(games).map(Number).sort((a, b) => a - b)
  const futureWeeks = weeks.filter(w => w >= currentWeek)

  return (
    <div className="overflow-x-auto">
      {/* Legend */}
      <div className="flex gap-3 mb-4 text-xs">
        {Object.entries(STATE_LABELS).map(([state, label]) => (
          <div key={state} className="flex items-center gap-1">
            <div className={clsx('w-3 h-3 rounded', STATE_CLASSES[state])} />
            <span className="text-slate-400">{label}</span>
          </div>
        ))}
      </div>

      <table className="w-full border-collapse text-xs">
        <thead>
          <tr>
            <th className="text-left text-slate-400 py-1 pr-3 font-medium w-12">Team</th>
            {futureWeeks.map(w => (
              <th
                key={w}
                className={clsx(
                  'text-center py-1 px-1 font-medium w-14',
                  w === currentWeek ? 'text-accent-blue' : 'text-slate-400'
                )}
              >
                W{w}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {ALL_TEAMS.map(team => (
            <tr key={team} className="border-t border-slate-800/50">
              <td className="py-1 pr-3 font-bold text-slate-200 text-xs">{team}</td>
              {futureWeeks.map(week => {
                const state = getCellState(team, week, games, entries, currentWeek)
                const prob = getWinProb(team, week, games)
                const probStr = prob !== null ? `${Math.round(prob * 100)}%` : ''
                return (
                  <td key={week} className="py-0.5 px-0.5">
                    <div
                      className={clsx(
                        'rounded text-center py-1 px-0.5 transition-colors',
                        STATE_CLASSES[state]
                      )}
                      title={state !== 'bye' ? `${team} wk${week}: ${probStr}` : 'BYE'}
                    >
                      {state === 'bye' ? '—' : (probStr || STATE_LABELS[state])}
                    </div>
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
