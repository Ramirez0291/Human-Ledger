import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { api, type AppStatus, type User } from './api/client'
import { AppShell } from './components/AppShell'
import { LedgerProvider } from './context/LedgerContext'
import { applyLocale } from './i18n'
import { AccountsPage } from './pages/AccountsPage'
import { ReportsPage } from './pages/ReportsPage'
import { DashboardPage } from './pages/DashboardPage'
import { ImportPage } from './pages/ImportPage'
import { LoginPage } from './pages/LoginPage'
import { SettingsPage } from './pages/SettingsPage'
import { SetupPage } from './pages/SetupPage'
import { TransactionsPage } from './pages/TransactionsPage'

export default function App() {
  const { t } = useTranslation()
  const [status, setStatus] = useState<AppStatus | null>(null)
  const [user, setUser] = useState<User | null>(null)
  const [authView, setAuthView] = useState<'login' | 'register'>('login')
  const [failed, setFailed] = useState(false)

  const load = useCallback(async () => {
    setFailed(false)
    try {
      const s = await api.status()
      setStatus(s)
      setUser(s.user)
      if (s.user?.locale) applyLocale(s.user.locale)
    } catch {
      setFailed(true)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const persistLocale = useCallback(
    (locale: string) => {
      if (!user) return
      void api.updateLocale(locale).catch(() => {
      })
    },
    [user],
  )

  const signOut = useCallback(async () => {
    await api.logout().catch(() => undefined)
    setUser(null)
    void load()
  }, [load])

  if (failed) {
    return (
      <div className="center-screen">
        <div className="auth-card">
          <h2>{t('common.error')}</h2>
          <p className="subtitle">Cannot reach the backend.</p>
          <button className="btn-primary" style={{ marginTop: 20 }} onClick={() => void load()}>
            {t('common.retry')}
          </button>
        </div>
      </div>
    )
  }

  if (!status) {
    return (
      <div className="center-screen">
        <p className="muted">{t('common.loading')}</p>
      </div>
    )
  }

  if (status.needs_setup) {
    return (
      <SetupPage
        onDone={(u) => {
          setUser(u)
          void load()
        }}
      />
    )
  }

  if (!user) {
    if (authView === 'register' && status.allow_registration) {
      return (
        <SetupPage
          mode="register"
          onBack={() => setAuthView('login')}
          onDone={(u) => {
            setUser(u)
            applyLocale(u.locale)
            void load()
          }}
        />
      )
    }
    return (
      <LoginPage
        onRegister={status.allow_registration ? () => setAuthView('register') : undefined}
        onDone={(u) => {
          setUser(u)
          applyLocale(u.locale)
          void load()
        }}
      />
    )
  }

  return (
    <LedgerProvider>
      <BrowserRouter>
        <Routes>
          <Route
            element={<AppShell onLogout={() => void signOut()} onPersistLocale={persistLocale} />}
          >
            <Route index element={<DashboardPage />} />
            <Route path="/transactions" element={<TransactionsPage />} />
            <Route path="/import" element={<ImportPage />} />
            <Route path="/import/:batchId" element={<ImportPage />} />
            <Route path="/reports" element={<ReportsPage />} />
            <Route path="/accounts" element={<AccountsPage />} />
            <Route path="/settings" element={<SettingsPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </LedgerProvider>
  )
}
