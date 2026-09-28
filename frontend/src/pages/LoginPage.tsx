import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ApiError, api, type User } from '../api/client'
import { BrandMark } from '../components/Icon'
import { LanguageSwitcher } from '../components/LanguageSwitcher'

interface Props {
  onDone: (user: User) => void
  onRegister?: () => void
}

export function LoginPage({ onDone, onRegister }: Props) {
  const { t } = useTranslation()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      const user = await api.login({ username, password })
      onDone(user)
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 401
          ? t('login.failed')
          : t('common.error'),
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="center-screen">
      <div className="auth-card">
        <div className="brand">
          <BrandMark />
          <h1>{t('app.name')}</h1>
        </div>

        <div style={{ marginTop: 20 }}>
          <LanguageSwitcher />
        </div>

        <h2 style={{ marginTop: 24 }}>{t('login.title')}</h2>

        <form onSubmit={submit}>
          {error && <div className="alert error">{error}</div>}

          <div className="field">
            <label htmlFor="login-username">{t('login.username')}</label>
            <input
              id="login-username"
              type="text"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
            />
          </div>

          <div className="field">
            <label htmlFor="login-password">{t('login.password')}</label>
            <input
              id="login-password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>

          <button className="btn-primary" type="submit" disabled={busy}>
            {busy ? t('login.submitting') : t('login.submit')}
          </button>
        </form>

        {onRegister && (
          <p className="auth-switch">
            {t('register.noAccount')}{' '}
            <button type="button" className="link-button" onClick={onRegister}>
              {t('register.title')}
            </button>
          </p>
        )}
      </div>
    </div>
  )
}
