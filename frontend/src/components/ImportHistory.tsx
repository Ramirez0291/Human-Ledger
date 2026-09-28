import { useCallback, useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate } from 'react-router-dom'
import { api, type ImportBatch } from '../api/client'
import { formatDateShort } from '../lib/format'

interface Props {
  onChanged?: () => void | Promise<void>
}

const SHOW = 8

export function ImportHistory({ onChanged }: Props) {
  const { t, i18n } = useTranslation()
  const locale = i18n.resolvedLanguage ?? 'zh-CN'
  const navigate = useNavigate()
  const [batches, setBatches] = useState<ImportBatch[]>([])
  const [all, setAll] = useState(false)
  const [busy, setBusy] = useState<number | null>(null)
  const [notice, setNotice] = useState('')

  const load = useCallback(async () => {
    const list = await api.importBatches()
    setBatches(list.filter((b) => b.status === 'confirmed' || b.status === 'reverted'))
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function act(b: ImportBatch, kind: 'revert' | 'overlaps') {
    const question =
      kind === 'revert'
        ? t('history.confirmRevert', { id: b.id, count: b.ledger_rows })
        : t('history.confirmOverlaps', { id: b.id, count: b.redundant_rows })
    if (!window.confirm(question)) return
    setBusy(b.id)
    try {
      const r = kind === 'revert' ? await api.revertBatch(b.id) : await api.removeBatchOverlaps(b.id)
      setNotice(t('history.removed', { count: r.removed }))
      await load()
      await onChanged?.()
    } finally {
      setBusy(null)
    }
  }

  if (!batches.length) return null
  const shown = all ? batches : batches.slice(0, SHOW)
  const anyOverlap = batches.some((b) => b.status === 'confirmed' && b.redundant_rows > 0)

  return (
    <div className="card">
      <div className="card-header">
        <h2>{t('history.title')}</h2>
      </div>
      <p className="card-desc">{t(anyOverlap ? 'history.descOverlap' : 'history.desc')}</p>
      {notice && (
        <div className="alert ok" style={{ marginTop: 10 }}>
          {notice}
        </div>
      )}
      <ul className="history-list">
        {shown.map((b) => {
          const reverted = b.status === 'reverted'
          const label = ([id, n]: [string, number]) =>
            id === '0' ? t('history.manual', { count: n }) : t('history.otherBatch', { id, count: n })
          const entries = Object.entries(b.overlaps).sort((x, y) => y[1] - x[1])
          const earlier = entries.filter(([id]) => Number(id) < b.id).map(label)
          const later = entries.filter(([id]) => Number(id) > b.id).map(label)
          const mostly = b.ledger_rows > 0 && b.redundant_rows >= b.ledger_rows * 0.9
          return (
            <li key={b.id} className={reverted ? 'reverted' : ''}>
              <div className="history-main">
                <div className="history-title">
                  <button type="button" className="btn-link mono" onClick={() => navigate(`/import/${b.id}`)}>
                    #{b.id}
                  </button>
                  <span>{new Date(b.created_at).toLocaleDateString(locale)}</span>
                  {reverted && <span className="badge">{t('history.reverted')}</span>}
                  <span className="muted small history-note" title={b.note ?? ''}>
                    {b.note}
                  </span>
                </div>
                {!reverted && (
                  <div className="muted small">
                    {t('history.meta', { count: b.ledger_rows })}
                    {b.account_names.length > 0 && ` · ${b.account_names.join('、')}`}
                    {b.date_from && b.date_to && ` · ${formatDateShort(b.date_from, locale)} – ${formatDateShort(b.date_to, locale)}`}
                  </div>
                )}
                {!reverted && b.redundant_rows > 0 && (
                  <div className="history-overlap">
                    {t(mostly ? 'history.overlapMostly' : 'history.overlap', {
                      count: b.redundant_rows,
                      with: earlier.join('、'),
                    })}
                  </div>
                )}
                {!reverted && b.redundant_rows === 0 && later.length > 0 && (
                  <div className="muted small">{t('history.overlapLater', { with: later.join('、') })}</div>
                )}
              </div>
              {!reverted && (
                <div className="history-actions">
                  {b.redundant_rows > 0 && (
                    <button
                      type="button"
                      className="btn-ghost small"
                      disabled={busy !== null}
                      onClick={() => void act(b, 'overlaps')}
                    >
                      {t('history.removeOverlaps', { count: b.redundant_rows })}
                    </button>
                  )}
                  <button
                    type="button"
                    className={`btn-ghost small ${mostly ? 'danger' : ''}`}
                    disabled={busy !== null || b.ledger_rows === 0}
                    onClick={() => void act(b, 'revert')}
                  >
                    {t('history.revert')}
                  </button>
                </div>
              )}
            </li>
          )
        })}
      </ul>
      {batches.length > SHOW && (
        <button type="button" className="btn-link" onClick={() => setAll((v) => !v)}>
          {all ? t('history.showLess') : t('history.showAll', { count: batches.length })}
        </button>
      )}
    </div>
  )
}
