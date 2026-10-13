import { useEffect } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { BrandMark, Icon, type IconName } from './Icon'
import { useLedger } from '../context/LedgerContext'
import { ComplianceBanner } from './ComplianceBanner'
import { LanguageSwitcher } from './LanguageSwitcher'

interface Props {
  onLogout: () => void
  onPersistLocale: (locale: string) => void
}

const NAV: { to: string; key: string; icon: IconName; end: boolean }[] = [
  { to: '/', key: 'nav.dashboard', icon: 'dashboard', end: true },
  { to: '/transactions', key: 'nav.transactions', icon: 'list', end: false },
  { to: '/reports', key: 'nav.reports', icon: 'chart', end: false },
  { to: '/budgets', key: 'nav.budget', icon: 'wallet', end: false },
  { to: '/import', key: 'nav.import', icon: 'import', end: false },
  { to: '/accounts', key: 'nav.accounts', icon: 'bank', end: false },
  { to: '/settings', key: 'nav.settings', icon: 'settings', end: false },
]

export function AppShell({ onLogout, onPersistLocale }: Props) {
  const { t } = useTranslation()
  const { compliance, refreshCompliance } = useLedger()
  const { pathname } = useLocation()

  // 换页时重算一次：在流水页补记完回到首页，气氛就该缓和了
  useEffect(() => {
    void refreshCompliance()
  }, [pathname, refreshCompliance])

  return (
    <div className="app-shell" data-tension={compliance ? compliance.level : undefined}>
      {/* 页头与导航合为一块吸顶玻璃，见 styles.css .app-top */}
      <div className="app-top">
        <header className="app-header">
          <span className="brand">
            <BrandMark />
            {t('app.name')}
          </span>
          <span className="spacer" />
          <LanguageSwitcher onPersist={onPersistLocale} />
          <button className="btn-ghost" onClick={onLogout}>
            <Icon name="logout" size={16} />
            {t('common.logout')}
          </button>
        </header>

        <nav className="app-nav" aria-label={t('nav.dashboard')}>
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => (isActive ? 'nav-item active' : 'nav-item')}
            >
              <Icon name={item.icon} />
              <span>{t(item.key)}</span>
            </NavLink>
          ))}
        </nav>
        {compliance && <ComplianceBanner data={compliance} />}
      </div>

      <main className="app-main">
        <Outlet />
      </main>
    </div>
  )
}
