import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ApiError, api, type User } from '../api/client'
import { BrandMark } from '../components/Icon'
import { LanguageSwitcher } from '../components/LanguageSwitcher'

interface Props {
  onDone: (user: User) => void
  /** setup：首次初始化（唯一入口）；register：已有用户时的自助注册 */
  mode?: 'setup' | 'register'
  onBack?: () => void
}

export function SetupPage({ onDone, mode = 'setup', onBack }: Props) {
  const { t, i18n } = useTranslation()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setError('')

    if (password.length < 8) {
      setError(t('setup.errorTooShort'))
      return
    }
    if (password !== confirm) {
      setError(t('setup.errorMismatch'))
      return
    }

    setBusy(true)
    try {
      const body = { username, password, locale: i18n.resolvedLanguage ?? 'zh-CN' }
      const user = mode === 'register' ? await api.register(body) : await api.setup(body)
      onDone(user)
    } catch (err) {
      setError(
        err instanceof ApiError
          ? t(`error.${err.detail}`, t('setup.errorFailed'))
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
        <p className="muted" style={{ fontSize: '0.8125rem' }}>
          {t('app.tagline')}
        </p>

        <div style={{ marginTop: 20 }}>
          <LanguageSwitcher />
        </div>

        <h2 style={{ marginTop: 24 }}>{t(mode === 'register' ? 'register.title' : 'setup.title')}</h2>
        <p className="subtitle">{t(mode === 'register' ? 'register.subtitle' : 'setup.subtitle')}</p>

        <form onSubmit={submit}>
          {error && <div className="alert error">{error}</div>}

          <div className="field">
            <label htmlFor="username">{t('setup.username')}</label>
            <input
              id="username"
              type="text"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
            />
          </div>

          <div className="field">
            <label htmlFor="password">{t('setup.password')}</label>
            <input
              id="password"
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
            <span className="hint">{t('setup.passwordHint')}</span>
          </div>

          <div className="field">
            <label htmlFor="confirm">{t('setup.passwordConfirm')}</label>
            <input
              id="confirm"
              type="password"
              autoComplete="new-password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              required
            />
          </div>

          <button className="btn-primary" type="submit" disabled={busy}>
            {busy ? t('setup.submitting') : t('setup.submit')}
          </button>
        </form>

        {mode === 'register' && onBack && (
          <p className="auth-switch">
            {t('register.haveAccount')}{' '}
            <button type="button" className="link-button" onClick={onBack}>
              {t('login.title')}
            </button>
          </p>
        )}
      </div>
    </div>
  )
}
