import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { useTranslation } from 'react-i18next'
import { api, type Account, type CategoryNode } from '../api/client'

interface LedgerContextValue {
  accounts: Account[]
  categories: CategoryNode[]
  categoryById: Map<number, CategoryNode>
  loading: boolean
  refreshAccounts: () => Promise<void>
  refreshCategories: () => Promise<void>
  refreshAll: () => Promise<void>
}

const LedgerContext = createContext<LedgerContextValue | null>(null)

function flatten(nodes: CategoryNode[], into: Map<number, CategoryNode>) {
  for (const n of nodes) {
    into.set(n.id, n)
    if (n.children.length) flatten(n.children, into)
  }
  return into
}

export function LedgerProvider({ children }: { children: ReactNode }) {
  const { i18n } = useTranslation()
  const locale = i18n.resolvedLanguage ?? 'zh-CN'

  const [accounts, setAccounts] = useState<Account[]>([])
  const [categories, setCategories] = useState<CategoryNode[]>([])
  const [loading, setLoading] = useState(true)

  const refreshAccounts = useCallback(async () => {
    setAccounts(await api.accounts())
  }, [])

  const refreshCategories = useCallback(async () => {
    setCategories(await api.categories(locale))
  }, [locale])

  const refreshAll = useCallback(async () => {
    setLoading(true)
    try {
      await Promise.all([refreshAccounts(), refreshCategories()])
    } finally {
      setLoading(false)
    }
  }, [refreshAccounts, refreshCategories])

  useEffect(() => {
    void refreshAll()
  }, [refreshAll])

  const categoryById = useMemo(() => flatten(categories, new Map()), [categories])

  const value = useMemo(
    () => ({
      accounts,
      categories,
      categoryById,
      loading,
      refreshAccounts,
      refreshCategories,
      refreshAll,
    }),
    [accounts, categories, categoryById, loading, refreshAccounts, refreshCategories, refreshAll],
  )

  return <LedgerContext.Provider value={value}>{children}</LedgerContext.Provider>
}

export function useLedger(): LedgerContextValue {
  const ctx = useContext(LedgerContext)
  if (!ctx) throw new Error('useLedger must be used inside LedgerProvider')
  return ctx
}
