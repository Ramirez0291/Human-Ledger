import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ApiError, api, type MatchType, type Rule } from '../api/client'
import { useLedger } from '../context/LedgerContext'

/**
 * 用户分类规则（判别链第 1 层）。
 *
 * 典型用途：SPOTIFY 每笔带不同交易号，商家记忆学不会；一条「包含 spotify → 订阅」
 * 就解决了。规则与规范化后的商家名比对，因此大小写、全半角、空格都无所谓。
 */
export function RulesPanel() {
  const { t } = useTranslation()
  const { categories, accounts } = useLedger()

  const [rules, setRules] = useState<Rule[]>([])
  const [pattern, setPattern] = useState('')
  const [matchType, setMatchType] = useState<MatchType>('contains')
  const [categoryId, setCategoryId] = useState<number | ''>('')
  const [accountId, setAccountId] = useState<number | ''>('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const flat = useMemo(() => categories.flatMap((c) => [c, ...c.children]), [categories])

  const load = useCallback(async () => setRules(await api.rules()), [])
  useEffect(() => {
    void load()
  }, [load])

  async function add(e: React.FormEvent) {
    e.preventDefault()
    if (!pattern.trim() || categoryId === '') return
    setError('')
    setBusy(true)
    try {
      await api.createRule({
        match_type: matchType,
        pattern: pattern.trim(),
        category_id: categoryId,
        account_id: accountId === '' ? null : accountId,
      })
      setPattern('')
      await load()
    } catch (err) {
      setError(err instanceof ApiError ? t(`error.${err.detail}`, t('common.error')) : t('common.error'))
    } finally {
      setBusy(false)
    }
  }

  async function toggle(rule: Rule) {
    await api.updateRule(rule.id, { enabled: !rule.enabled })
    await load()
  }

  async function remove(rule: Rule) {
    if (!window.confirm(t('rules.confirmDelete'))) return
    await api.deleteRule(rule.id)
    await load()
  }

  return (
    <div className="card">
      <div className="card-header">
        <h2>{t('rules.title')}</h2>
      </div>
      <p className="card-desc">{t('rules.desc')}</p>

      <form onSubmit={add} className="rule-form">
        {error && <div className="alert error">{error}</div>}
        <select value={matchType} onChange={(e) => setMatchType(e.target.value as MatchType)}>
          <option value="contains">{t('rules.contains')}</option>
          <option value="exact">{t('rules.exact')}</option>
          <option value="regex">{t('rules.regex')}</option>
        </select>
        <input
          type="text"
          placeholder={t('rules.patternPlaceholder')}
          value={pattern}
          onChange={(e) => setPattern(e.target.value)}
        />
        <span className="muted">→</span>
        <select
          value={categoryId}
          onChange={(e) => setCategoryId(e.target.value ? Number(e.target.value) : '')}
        >
          <option value="">{t('form.category')}</option>
          {flat.map((c) => (
            <option key={c.id} value={c.id}>
              {c.parent_id ? '　' : ''}
              {c.name}
            </option>
          ))}
        </select>
        <select
          value={accountId}
          onChange={(e) => setAccountId(e.target.value ? Number(e.target.value) : '')}
        >
          <option value="">{t('rules.anyAccount')}</option>
          {accounts.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
        <button className="btn-primary" type="submit" disabled={busy || !pattern.trim() || categoryId === ''}>
          {t('rules.add')}
        </button>
      </form>

      {rules.length === 0 ? (
        <p className="muted" style={{ marginTop: 12 }}>
          {t('rules.empty')}
        </p>
      ) : (
        <ul className="rule-list">
          {rules.map((r) => (
            <li key={r.id} className={r.enabled ? '' : 'disabled'}>
              <span className="tag">{t(`rules.${r.match_type}`)}</span>
              <code className="rule-pattern">{r.pattern}</code>
              <span className="muted">→</span>
              <span>{r.category_name ?? r.category_id}</span>
              {r.account_id && (
                <span className="muted">
                  · {accounts.find((a) => a.id === r.account_id)?.name ?? r.account_id}
                </span>
              )}
              <span className="spacer" />
              <button className="btn-ghost" onClick={() => void toggle(r)}>
                {r.enabled ? t('rules.disable') : t('rules.enable')}
              </button>
              <button className="btn-ghost danger" onClick={() => void remove(r)}>
                {t('common.delete')}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
