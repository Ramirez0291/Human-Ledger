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

/**
 * 账户与类目是几乎每个页面都要用的参照数据，且改动不频繁，
 * 因此集中取一次并缓存，避免每个页面各自请求。
 *
 * 类目名称随语言变化（后端按 locale 返回），所以语言切换时必须重新拉取。
 */
interface LedgerContextValue {
  accounts: Account[]
  categories: CategoryNode[]
  /** 扁平化的类目索引，便于按 id 查名称 */
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
  if (!ctx) throw new Error('useLedger 必须在 LedgerProvider 内使用')
  return ctx
}
