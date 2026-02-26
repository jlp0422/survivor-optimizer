import { NavLink } from 'react-router-dom'
import { clsx } from 'clsx'

const links = [
  { to: '/',            label: 'Dashboard' },
  { to: '/schedule',   label: 'Season Calendar' },
  { to: '/simulation', label: 'Simulation' },
]

export default function Nav() {
  return (
    <nav className="border-b border-slate-700/50 bg-surface-card">
      <div className="max-w-7xl mx-auto px-4 flex items-center gap-6 h-14">
        <span className="font-bold text-white tracking-tight mr-2">
          🏈 Survivor Optimizer
        </span>
        {links.map(({ to, label }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              clsx(
                'text-sm font-medium transition-colors pb-0.5 border-b-2',
                isActive
                  ? 'text-white border-accent-blue'
                  : 'text-slate-400 border-transparent hover:text-slate-200'
              )
            }
          >
            {label}
          </NavLink>
        ))}
      </div>
    </nav>
  )
}
