import { clsx } from 'clsx'

interface PickCardProps {
  team: string
  opponent: string | null
  isHome: boolean
  winProb: number
  survivalProb?: number
  isRecommended?: boolean
  isUsed?: boolean
  isSelected?: boolean
  onClick?: () => void
}

// NFL team colors for visual identity
const TEAM_COLORS: Record<string, string> = {
  ARI: '#97233f', ATL: '#a71930', BAL: '#241773', BUF: '#00338d',
  CAR: '#0085ca', CHI: '#0b162a', CIN: '#fb4f14', CLE: '#311d00',
  DAL: '#003594', DEN: '#fb4f14', DET: '#0076b6', GB:  '#203731',
  HOU: '#03202f', IND: '#002c5f', JAX: '#006778', KC:  '#e31837',
  LAC: '#0080c6', LAR: '#003594', LV:  '#000000', MIA: '#008e97',
  MIN: '#4f2683', NE:  '#002244', NO:  '#d3bc8d', NYG: '#0b2265',
  NYJ: '#125740', PHI: '#004c54', PIT: '#ffb612', SEA: '#002244',
  SF:  '#aa0000', TB:  '#d50a0a', TEN: '#0c2340', WAS: '#773141',
}

function winProbColor(prob: number): string {
  if (prob >= 0.75) return 'bg-accent-green'
  if (prob >= 0.60) return 'bg-yellow-500'
  if (prob >= 0.50) return 'bg-orange-500'
  return 'bg-accent-red'
}

export default function PickCard({
  team,
  opponent,
  isHome,
  winProb,
  survivalProb,
  isRecommended,
  isUsed,
  isSelected,
  onClick,
}: PickCardProps) {
  const teamColor = TEAM_COLORS[team] ?? '#334155'
  const pct = Math.round(winProb * 100)
  const survPct = survivalProb !== undefined ? Math.round(survivalProb * 100) : null

  return (
    <button
      onClick={onClick}
      disabled={isUsed}
      className={clsx(
        'relative w-full text-left rounded-xl border transition-all duration-200 overflow-hidden',
        isUsed && 'opacity-40 cursor-not-allowed grayscale',
        isSelected && 'ring-2 ring-accent-blue border-accent-blue',
        !isSelected && !isUsed && 'border-slate-700/50 hover:border-slate-500 hover:shadow-lg hover:shadow-black/30',
        isRecommended && !isSelected && 'border-accent-green/50',
      )}
    >
      {/* Color accent strip */}
      <div
        className="absolute left-0 top-0 bottom-0 w-1"
        style={{ backgroundColor: teamColor }}
      />

      <div className="pl-4 p-3">
        {/* Header row */}
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <span className="text-xl font-bold tracking-tight">{team}</span>
            {isRecommended && (
              <span className="text-[10px] font-semibold bg-accent-green/20 text-accent-green px-1.5 py-0.5 rounded-full">
                PICK
              </span>
            )}
            {isUsed && (
              <span className="text-[10px] font-semibold bg-slate-600/50 text-slate-400 px-1.5 py-0.5 rounded-full">
                USED
              </span>
            )}
          </div>
          <span className={clsx(
            'text-lg font-bold',
            winProb >= 0.75 ? 'text-accent-green' :
            winProb >= 0.60 ? 'text-yellow-400' :
            winProb >= 0.50 ? 'text-orange-400' : 'text-red-400'
          )}>
            {pct}%
          </span>
        </div>

        {/* Opponent */}
        {opponent && (
          <div className="text-xs text-slate-400 mb-2">
            {isHome ? 'vs' : '@'} {opponent}
          </div>
        )}

        {/* Win probability bar */}
        <div className="win-bar mb-1">
          <div
            className={clsx('win-bar-fill', winProbColor(winProb))}
            style={{ width: `${pct}%` }}
          />
        </div>
        <div className="flex justify-between text-[10px] text-slate-500">
          <span>Win prob</span>
          {survPct !== null && (
            <span className="text-slate-400">Survival: {survPct}%</span>
          )}
        </div>
      </div>
    </button>
  )
}
