const BASE = '/api'

async function fetchJSON<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail ?? `HTTP ${res.status}`)
  }
  return res.json()
}

// ── Types ──────────────────────────────────────────────────────────────────

export interface Game {
  id: number
  season: number
  week: number
  game_date: string | null
  home_team: string
  away_team: string
  home_score: number | null
  away_score: number | null
  home_win: boolean | null
  home_win_prob: number | null
  away_win_prob: number | null
  is_neutral: boolean
}

export interface ScheduleResponse {
  season: number
  weeks: Record<number, Game[]>
}

export interface Entry {
  id: number
  name: string
  season: number
  is_alive: boolean
  eliminated_week: number | null
  created_at: string
  used_teams: string[]
}

export interface Pick {
  id: number
  entry_id: number
  team: string
  season: number
  week: number
  win_prob: number | null
  is_recommended: boolean
  outcome: boolean | null
  submitted_at: string
}

export interface PickRecommendation {
  entry_id: number
  week: number
  recommended_team: string
  win_prob: number | null
  survival_prob: number
  portfolio_coverage: number
  strategy_picks: Record<number, string>
}

export interface RecommendResponse {
  season: number
  week: number
  recommendations: PickRecommendation[]
}

export interface TeamSurvivalProb {
  team: string
  win_prob: number
  survival_prob: number
  opponent: string | null
  is_home: boolean
}

export interface SimulationResponse {
  season: number
  week: number
  n_simulations: number
  team_survival_probs: TeamSurvivalProb[]
  scarcity_by_week: Record<number, number>
}

export interface TeamGameSchema {
  week: number
  opponent: string
  is_home: boolean
  win_prob: number | null
  is_played: boolean
  result: 'W' | 'L' | null
}

export interface TeamScheduleResponse {
  team: string
  season: number
  games: TeamGameSchema[]
  used_by_entries: number[]
}

export interface UpdateResponse {
  season: number
  week: number
  games_updated: number
  win_probs_updated: number
  message: string
}

// ── API calls ──────────────────────────────────────────────────────────────

export const api = {
  getSchedule: (season: number) =>
    fetchJSON<ScheduleResponse>(`/schedule/${season}`),

  getEntries: (season?: number) =>
    fetchJSON<Entry[]>(`/entries${season ? `?season=${season}` : ''}`),

  createEntry: (name: string, season: number) =>
    fetchJSON<Entry>('/entries', {
      method: 'POST',
      body: JSON.stringify({ name, season }),
    }),

  submitPick: (entryId: number, teamAbbr: string, season: number, week: number) =>
    fetchJSON<Pick>('/picks/submit', {
      method: 'POST',
      body: JSON.stringify({ entry_id: entryId, team_abbr: teamAbbr, season, week }),
    }),

  getRecommendations: (week: number, season: number) =>
    fetchJSON<RecommendResponse>(`/picks/recommend/${week}?season=${season}`),

  runSimulation: (week: number, season: number, entryId?: number, nSims = 50000) =>
    fetchJSON<SimulationResponse>(
      `/simulate/${week}?season=${season}&n_simulations=${nSims}${entryId ? `&entry_id=${entryId}` : ''}`
    ),

  getTeamSchedule: (teamAbbr: string, season: number) =>
    fetchJSON<TeamScheduleResponse>(`/teams/${teamAbbr}/schedule?season=${season}`),

  updateResults: (season: number, week: number) =>
    fetchJSON<UpdateResponse>(`/results/update/${week}`, {
      method: 'POST',
      body: JSON.stringify({ season, week }),
    }),
}
