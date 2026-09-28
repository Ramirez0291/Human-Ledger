import { useTranslation } from 'react-i18next'
import type { CategoryNode } from '../api/client'

interface Props {
  categories: CategoryNode[]
  value: number | null
  onChange: (id: number | null) => void
  type: 'expense' | 'income'
  id?: string
  suggested?: boolean
}

export function CategorySelect({ categories, value, onChange, type, id, suggested }: Props) {
  const { t } = useTranslation()
  const groups = categories.filter((c) => c.type === type)

  return (
    <div className="category-select">
      <select
        id={id}
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
      >
        <option value="">{t('form.noCategory')}</option>
        {groups.map((g) =>
          g.children.length ? (
            <optgroup key={g.id} label={`${g.icon ?? ''} ${g.name}`}>
              <option value={g.id}>{g.name}</option>
              {g.children.map((c) => (
                <option key={c.id} value={c.id}>
                  {'　'}
                  {c.name}
                </option>
              ))}
            </optgroup>
          ) : (
            <option key={g.id} value={g.id}>
              {g.icon} {g.name}
            </option>
          ),
        )}
      </select>
      {suggested && <span className="suggest-badge">{t('form.autoFilled')}</span>}
    </div>
  )
}
