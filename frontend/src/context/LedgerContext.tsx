import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { api, type Account, type CategoryNode, type Compliance, type LedgerMode } from '../api/client'

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
  /** 记账风格：轻松（余额以最近的真实余额为准、不催对账）/ 严谨 */
  ledgerMode: LedgerMode
  setLedgerMode: (mode: LedgerMode) => Promise<void>
  /** 合规模式下的账面紧张度；轻松模式恒为 null */
  compliance: Compliance | null
  refreshCompliance: () => Promise<void>
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
  const [ledgerMode, setMode] = useState<LedgerMode>('relaxed')
  const [compliance, setCompliance] = useState<Compliance | null>(null)

  const refreshCompliance = useCallback(async () => {
    try {
      const c = await api.compliance()
      setCompliance(c.mode === 'strict' ? c : null)
    } catch {
      setCompliance(null)
    }
  }, [])

  // 余额一变（记账、对账、导入之后都会调这里），合规紧张度跟着重算
  const refreshAccounts = useCallback(async () => {
    const [list] = await Promise.all([api.accounts(), refreshCompliance()])
    setAccounts(list)
  }, [refreshCompliance])

  const refreshCategories = useCallback(async () => {
    setCategories(await api.categories(locale))
  }, [locale])

  const setLedgerMode = useCallback(
    async (mode: LedgerMode) => {
      setMode((await api.setPreferences({ ledger_mode: mode })).ledger_mode)
      // 两种风格的余额算法不同，切换后账户余额要重取
      await refreshAccounts()
    },
    [refreshAccounts],
  )

  const refreshAll = useCallback(async () => {
    setLoading(true)
    try {
      await Promise.all([
        refreshAccounts(),
        refreshCategories(),
        api
          .preferences()
          .then((p) => setMode(p.ledger_mode))
          .catch(() => undefined),
      ])
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
      ledgerMode,
      setLedgerMode,
      compliance,
      refreshCompliance,
    }),
    [
      accounts,
      categories,
      categoryById,
      loading,
      refreshAccounts,
      refreshCategories,
      refreshAll,
      ledgerMode,
      setLedgerMode,
      compliance,
      refreshCompliance,
    ],
  )

  return <LedgerContext.Provider value={value}>{children}</LedgerContext.Provider>
}

export function useLedger(): LedgerContextValue {
  const ctx = useContext(LedgerContext)
  if (!ctx) throw new Error('useLedger 必须在 LedgerProvider 内使用')
  return ctx
}
