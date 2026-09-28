import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ApiError, api, type CategoryNode } from '../api/client'
import { useLedger } from '../context/LedgerContext'
import { SUPPORTED_LOCALES } from '../i18n'
import { Modal } from './Modal'

interface Props {
  /** 只显示这一类（待确认区按行的收支方向传）；不传则两类都显示 */
  type?: 'expense' | 'income'
  /** 传了就变成「可选取」模式：点类目名把它交给调用方（待确认区里直接给行赋类别） */
  onPick?: (c: CategoryNode) => void
}

/**
 * 类目的增删改查。设置页与待确认区共用——用户在核对导入数据时
 * 发现类目不够用，不必离开当前页去设置里加。
 */
export function CategoryManager({ type, onPick }: Props) {
  const { t } = useTranslation()
  const { categories, refreshCategories } = useLedger()

  const [query, setQuery] = useState('')
  const [editing, setEditing] = useState<CategoryNode | null>(null)
  const [creatingUnder, setCreatingUnder] = useState<CategoryNode | null | 'root'>(null)

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return categories
      .filter((g) => !type || g.type === type)
      .map((g) => ({
        ...g,
        children: q ? g.children.filter((c) => c.name.toLowerCase().includes(q)) : g.children,
      }))
      .filter((g) => !q || g.name.toLowerCase().includes(q) || g.children.length > 0)
  }, [categories, type, query])

  async function toggleHidden(c: CategoryNode) {
    await api.updateCategory(c.id, { is_hidden: !c.is_hidden })
    await refreshCategories()
  }

  async function remove(c: CategoryNode) {
    if (!window.confirm(t('category.confirmDelete'))) return
    try {
      await api.deleteCategory(c.id)
      await refreshCategories()
    } catch (err) {
      if (err instanceof ApiError) window.alert(t(`error.${err.detail}`, t('common.error')))
    }
  }

  function closeForm() {
    setEditing(null)
    setCreatingUnder(null)
  }

  return (
    <>
      <div className="cat-manage-toolbar">
        <input
          type="search"
          className="cat-manage-search"
          placeholder={t('category.search')}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <button className="btn-ghost" onClick={() => setCreatingUnder('root')}>
          {t('category.addTop')}
        </button>
      </div>

      <div className="cat-manage">
        {visible.map((g) => (
          <div className="cat-manage-group" key={g.id}>
            <div className="cat-manage-head">
              <span aria-hidden="true">{g.icon}</span>
              {onPick ? (
                <button className="cat-pick" onClick={() => onPick(g)}>
                  {g.name}
                </button>
              ) : (
                <span className={g.is_hidden ? 'muted' : ''}>{g.name}</span>
              )}
              {g.is_system && <span className="tag">{t('category.system')}</span>}
              {g.is_hidden && <span className="tag">{t('category.hidden')}</span>}
              <span className="spacer" />
              <button className="btn-ghost" onClick={() => setCreatingUnder(g)}>
                {t('category.addChild')}
              </button>
              <button className="btn-ghost" onClick={() => setEditing(g)}>
                {t('common.edit')}
              </button>
              <button className="btn-ghost" onClick={() => void toggleHidden(g)}>
                {g.is_hidden ? t('category.show') : t('category.hide')}
              </button>
              {!g.is_system && (
                <button className="btn-ghost danger" onClick={() => void remove(g)}>
                  {t('common.delete')}
                </button>
              )}
            </div>
            {g.children.length > 0 && (
              <div className="cat-manage-children">
                {g.children.map((c) => (
                  <span className="cat-chip" key={c.id}>
                    {onPick ? (
                      <button className="cat-pick" onClick={() => onPick(c)}>
                        {c.name}
                      </button>
                    ) : (
                      <span className={c.is_hidden ? 'muted' : ''}>{c.name}</span>
                    )}
                    <button
                      className="chip-btn"
                      onClick={() => setEditing(c)}
                      aria-label={t('common.edit')}
                    >
                      ✎
                    </button>
                    {!c.is_system && (
                      <button
                        className="chip-btn danger"
                        onClick={() => void remove(c)}
                        aria-label={t('common.delete')}
                      >
                        ×
                      </button>
                    )}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
        {visible.length === 0 && <p className="muted">{t('category.noMatch')}</p>}
      </div>

      <Modal
        open={editing !== null || creatingUnder !== null}
        title={editing ? t('category.edit') : t('category.add')}
        onClose={closeForm}
      >
        <CategoryForm
          existing={editing}
          parent={creatingUnder === 'root' ? null : creatingUnder}
          defaultType={type}
          onSaved={async (created) => {
            closeForm()
            await refreshCategories()
            if (created && onPick) onPick(created)
          }}
          onCancel={closeForm}
        />
      </Modal>
    </>
  )
}

// --------------------------------------------------------------------------

export function CategoryForm({
  existing,
  parent,
  defaultType,
  onSaved,
  onCancel,
}: {
  existing: CategoryNode | null
  parent: CategoryNode | null
  defaultType?: 'expense' | 'income'
  /** 新建时把创建出来的类目交回去，调用方可以立刻用上 */
  onSaved: (created: CategoryNode | null) => void
  onCancel: () => void
}) {
  const { t } = useTranslation()
  const [names, setNames] = useState<Record<string, string>>(existing?.names ?? {})
  const [icon, setIcon] = useState(existing?.icon ?? '')
  const [type, setType] = useState<'expense' | 'income'>(
    existing?.type ?? parent?.type ?? defaultType ?? 'expense',
  )
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setError('')

    const filled = Object.fromEntries(
      Object.entries(names).filter(([, v]) => v.trim()),
    ) as Record<string, string>
    if (Object.keys(filled).length === 0) {
      setError(t('category.errorNoName'))
      return
    }

    setBusy(true)
    try {
      if (existing) {
        await api.updateCategory(existing.id, { names: filled, icon: icon || null })
        onSaved(null)
      } else {
        const created = await api.createCategory({
          parent_id: parent?.id ?? null,
          type,
          icon: icon || null,
          names: filled,
        })
        onSaved(created)
      }
    } catch (err) {
      setError(err instanceof ApiError ? t(`error.${err.detail}`, t('common.error')) : t('common.error'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="txn-form">
      {error && <div className="alert error">{error}</div>}

      {parent && (
        <p className="alert info">{t('category.parentIs', { name: parent.name })}</p>
      )}

      {!existing && !parent && (
        <div className="field">
          <label htmlFor="cat-type">{t('category.type')}</label>
          <select
            id="cat-type"
            value={type}
            onChange={(e) => setType(e.target.value as 'expense' | 'income')}
          >
            <option value="expense">{t('direction.expense')}</option>
            <option value="income">{t('direction.income')}</option>
          </select>
        </div>
      )}

      <div className="field">
        <label htmlFor="cat-icon">{t('category.icon')}</label>
        <input
          id="cat-icon"
          type="text"
          maxLength={4}
          value={icon}
          onChange={(e) => setIcon(e.target.value)}
          placeholder="🍚"
        />
      </div>

      {/* 每种语言各一个输入框：类目名是业务数据，必须按语言分别存 */}
      {SUPPORTED_LOCALES.map((loc) => (
        <div className="field" key={loc.code}>
          <label htmlFor={`cat-name-${loc.code}`}>{loc.nativeName}</label>
          <input
            id={`cat-name-${loc.code}`}
            type="text"
            value={names[loc.code] ?? ''}
            onChange={(e) => setNames({ ...names, [loc.code]: e.target.value })}
            autoFocus={loc.code === SUPPORTED_LOCALES[0]?.code}
          />
        </div>
      ))}
      <p className="hint">{t('category.nameHint')}</p>

      <div className="form-actions">
        <button type="button" className="btn-ghost" onClick={onCancel}>
          {t('common.cancel')}
        </button>
        <button type="submit" className="btn-primary" disabled={busy}>
          {busy ? t('common.saving') : t('common.save')}
        </button>
      </div>
    </form>
  )
}
