/** 后端 API 封装。会话走 HttpOnly Cookie，因此所有请求都要带 credentials。 */

export class ApiError extends Error {
  constructor(
    public status: number,
    public detail: string,
  ) {
    super(detail)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`/api${path}`, {
    credentials: 'include',
    headers: init.body ? { 'Content-Type': 'application/json' } : undefined,
    ...init,
  })

  if (res.status === 204) return undefined as T

  let payload: unknown = null
  const text = await res.text()
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = text
    }
  }

  if (!res.ok) {
    const detail =
      typeof payload === 'object' && payload !== null && 'detail' in payload
        ? typeof (payload as { detail: unknown }).detail === 'string'
          ? String((payload as { detail: unknown }).detail)
          : 'validation_error'
        : `http_${res.status}`
    throw new ApiError(res.status, detail)
  }

  return payload as T
}

/** multipart 上传：不能手动设 Content-Type，浏览器要自己带 boundary。 */
async function upload<T>(path: string, form: FormData): Promise<T> {
  const res = await fetch(`/api${path}`, { method: 'POST', credentials: 'include', body: form })
  const text = await res.text()
  let payload: unknown = null
  if (text) {
    try {
      payload = JSON.parse(text)
    } catch {
      payload = text
    }
  }
  if (!res.ok) {
    const detail =
      typeof payload === 'object' && payload !== null && 'detail' in payload
        ? typeof (payload as { detail: unknown }).detail === 'string'
          ? String((payload as { detail: unknown }).detail)
          : 'validation_error'
        : `http_${res.status}`
    throw new ApiError(res.status, detail)
  }
  return payload as T
}

function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === '') continue
    sp.set(k, String(v))
  }
  const s = sp.toString()
  return s ? `?${s}` : ''
}

// ---- 基础类型 ----

export interface User {
  id: number
  username: string
  locale: string
}

export interface AppStatus {
  needs_setup: boolean
  authenticated: boolean
  allow_registration: boolean
  user: User | null
  default_locale: string
  supported_locales: string[]
  app_name: string
  version: string
}

export interface SystemInfo {
  table_count: number
  tables: string[]
  migration_revision: string | null
  timezone: string
  database: string
}

export interface OcrProviderInfo {
  key: string
  available: boolean
  /** i18n 词条 key，由前端翻译；后端不返回已翻译文案（需求书 F10） */
  reason_key: string
  active: boolean
}

export interface OcrProviders {
  active: string
  providers: OcrProviderInfo[]
  note_key: string
}

// ---- 账户 ----

export type AccountType = 'cash' | 'bank' | 'credit_card' | 'emoney' | 'prepaid' | 'investment'

export interface Account {
  id: number
  name: string
  type: AccountType
  institution: string | null
  opening_balance: number
  opening_date: string | null
  closing_day: number | null
  payment_day: number | null
  color: string | null
  sort_order: number
  is_archived: boolean
  balance: number
  transaction_count: number
  last_reconcile_diff: number | null
  last_reconcile_date: string | null
}

export interface AccountInput {
  name: string
  type: AccountType
  institution?: string | null
  opening_balance?: number
  opening_date?: string | null
  closing_day?: number | null
  payment_day?: number | null
  color?: string | null
  sort_order?: number
  is_archived?: boolean
}

export interface ReconcileResult {
  date: string
  actual_balance: number
  computed_balance: number
  diff: number
}

// ---- 类目 ----

export interface CategoryNode {
  id: number
  key: string
  parent_id: number | null
  name: string
  names: Record<string, string>
  type: 'expense' | 'income'
  icon: string | null
  color: string | null
  is_system: boolean
  is_hidden: boolean
  children: CategoryNode[]
}

// ---- 交易 ----

export type Direction = 'expense' | 'income' | 'transfer_out' | 'transfer_in'

export interface Transaction {
  id: number
  account_id: number
  account_name: string
  date: string
  time: string | null
  direction: Direction
  amount: number
  merchant_raw: string
  merchant_norm: string
  category_id: number | null
  category_key: string | null
  category_name: string | null
  category_icon: string | null
  category_color: string | null
  memo: string | null
  source: 'manual' | 'screenshot' | 'csv' | 'recurring'
  transfer_group_id: string | null
  installment_current: number | null
  installment_total: number | null
  installment_total_amount: number | null
  exclude_from_analysis: boolean
  deleted_at: string | null
}

export interface TransactionInput {
  account_id: number
  date: string
  direction: 'expense' | 'income'
  amount: number
  merchant_raw?: string
  category_id?: number | null
  memo?: string | null
  installment_current?: number | null
  installment_total?: number | null
  installment_total_amount?: number | null
  exclude_from_analysis?: boolean
}

export interface TransferInput {
  from_account_id: number
  to_account_id: number
  date: string
  amount: number
  memo?: string | null
  fee?: number
  fee_category_id?: number | null
}

export interface TransactionPage {
  items: Transaction[]
  total: number
  page: number
  page_size: number
  sum_income: number
  sum_expense: number
}

export interface TransactionFilters {
  date_from?: string
  date_to?: string
  account_id?: number
  category_id?: number
  direction?: Direction
  q?: string
  include_deleted?: boolean
  page?: number
  page_size?: number
}

// ---- 总览 ----

export interface Summary {
  year_month: string
  income: number
  expense: number
  net: number
  accounts: { id: number; name: string; type: AccountType; color: string | null; balance: number }[]
  total_balance: number
  expense_breakdown: {
    category_id: number
    key: string
    name: string
    icon: string | null
    color: string | null
    amount: number
  }[]
  uncategorized_expense: number
  reconcile_alerts: { account_id: number; account_name: string; date: string; diff: number }[]
  transaction_count: number
}


// ---- 报表 ----

export interface ReportFilters {
  account_id?: number
  category_id?: number
  q?: string
  /** true 时把标记为除外的交易也算进来 */
  include_flagged?: boolean
  /** 单笔支出超过此金额不计入分析 */
  max_single?: number
  /** 逗号分隔的类目 id */
  exclude_categories?: string
}

export interface ReportTotals {
  income: number
  expense: number
  net: number
  count: number
}

export interface CategoryShare {
  category_id: number
  key: string
  name: string
  icon: string | null
  amount: number
  count: number
  share: number
}

export interface CategoryGroup extends CategoryShare {
  color: string | null
  children: CategoryShare[]
}

export interface CategoryBreakdown {
  total: number
  uncategorized: number
  items: CategoryGroup[]
}

export interface ReportOverview {
  year_month: string
  totals: ReportTotals
  /** 除外之前的原貌 */
  raw_totals: ReportTotals
  excluded: { expense: number; income: number; count: number }
  previous: ReportTotals
  expense_by_category: CategoryBreakdown
  income_by_category: CategoryBreakdown
  top_merchants: { merchant_norm: string; merchant: string; amount: number; count: number }[]
  accounts: {
    id: number
    name: string
    type: AccountType
    color: string | null
    balance: number
    month_delta: number
    month_income: number
    month_expense: number
  }[]
}

export interface TrendMonth {
  month: string
  income: number
  expense: number
  net: number
  excluded_expense: number
  excluded_income: number
}

export interface DailyReport {
  year_month: string
  days: { day: number; expense: number; excluded: number }[]
  previous: { day: number; expense: number }[]
}

export interface LargeExpense {
  id: number
  date: string
  merchant: string
  amount: number
  category_id: number | null
  category_name: string | null
  category_icon: string | null
  exclude_from_analysis: boolean
  over_threshold: boolean
  account_id: number
  account_name: string
  /** 像信用卡还款 / 取现 / 充值 / 转入证券：钱只是换了账户 */
  transfer_like: boolean
  suggested_counterpart_id: number | null
}

// ---- 导入 / 待确认区 ----

export type DupStatus = 'none' | 'merged' | 'duplicate' | 'maybe'
export type CategorySource = 'rule' | 'memory' | 'dictionary' | 'llm' | 'none'
export type BatchStatus = 'draft' | 'confirmed' | 'discarded' | 'reverted'

export interface StagedRow {
  id: number
  batch_id: number
  account_id: number | null
  account_name: string
  date: string | null
  time: string | null
  direction: Direction | null
  amount: number | null
  merchant_raw: string
  merchant_norm: string
  category_id: number | null
  category_name: string | null
  category_icon: string | null
  category_color: string | null
  memo: string | null
  confidence: number
  category_confidence: number
  category_source: CategorySource
  date_inferred: boolean
  dup_status: DupStatus
  dup_reason: string | null
  dup_ref_id: number | null
  merged_count: number
  excluded: boolean
  exclude_reason: string | null
  merged_into_id: number | null
  balance_after: number | null
  transfer_hint: boolean
  counterpart_account_id: number | null
  is_selected: boolean
  installment_current: number | null
  installment_total: number | null
  installment_total_amount: number | null
  raw_text: string | null
}

export interface ImportBatch {
  id: number
  source_type: string
  status: BatchStatus
  file_count: number
  note: string | null
  created_at: string
  total_rows: number
  selected_rows: number
  excluded_rows: number
  duplicate_rows: number
  maybe_rows: number
  /** 已确认 / 已撤销批次的入账概况 */
  ledger_rows: number
  date_from: string | null
  date_to: string | null
  account_names: string[]
  overlap_rows: number
  /** 其中与更早的记录重叠的行（这批是多出来的那份） */
  redundant_rows: number
  /** 与哪个批次重叠多少行；键 0 = 手动记账 */
  overlaps: Record<string, number>
}

export interface BatchActionResult {
  removed: number
  batch: ImportBatch
}

export interface BatchDetail {
  batch: ImportBatch
  rows: StagedRow[]
  warnings: string[]
  detected_balance: number | null
  statement_month: string | null
  previously_imported: boolean
}

export interface StagedRowUpdate {
  account_id?: number
  date?: string
  direction?: 'expense' | 'income'
  amount?: number
  merchant_raw?: string
  category_id?: number
  memo?: string
  is_selected?: boolean
  counterpart_account_id?: number
  clear_counterpart?: boolean
  clear_category?: boolean  /** 改类别时连带同批次里同商家 / 同品牌的行（默认开） */
  apply_to_similar?: boolean
}

export interface StagedRowPatch {
  row: StagedRow
  /** 因 apply_to_similar 被连带改掉的行 */
  affected: StagedRow[]
}

export interface ConfirmResult {
  imported: number
  transfers: number
  skipped_unselected: number
  skipped_excluded: number
  skipped_incomplete: number
  skipped_duplicate: number
  reconcile: {
    account_id: number
    account_name: string
    date: string
    actual_balance: number
    computed_balance: number
    diff: number
  } | null
  warnings: string[]
}

// ---- CSV ----

export interface ColumnMapping {
  date: number
  merchant: number
  amount?: number | null
  withdrawal?: number | null
  deposit?: number | null
  balance?: number | null
  memo?: number | null
  positive_is_expense?: boolean
  has_header?: boolean
  skip_rows?: number
}

export interface CsvFilePreview {
  filename: string
  encoding: string
  profile: string | null
  profile_name: string | null
  account_kind: string | null
  header: string[]
  sample: string[][]
  row_count: number
  mapping: ColumnMapping | null
  statement_month: string | null
  previously_imported: boolean
  warnings: string[]
}

export interface CsvPreview {
  files: CsvFilePreview[]
  suggested_account_id: number | null
}

// ---- 规则 ----

export type MatchType = 'exact' | 'contains' | 'regex'

export interface Rule {
  id: number
  match_type: MatchType
  pattern: string
  category_id: number
  category_name: string | null
  account_id: number | null
  priority: number
  enabled: boolean
}

// ---- 接口 ----

export const api = {
  // 认证
  status: () => request<AppStatus>('/status'),
  setup: (body: { username: string; password: string; locale: string }) =>
    request<User>('/setup', { method: 'POST', body: JSON.stringify(body) }),
  register: (body: { username: string; password: string; locale: string }) =>
    request<User>('/register', { method: 'POST', body: JSON.stringify(body) }),
  login: (body: { username: string; password: string }) =>
    request<User>('/login', { method: 'POST', body: JSON.stringify(body) }),
  logout: () => request<void>('/logout', { method: 'POST' }),
  updateLocale: (locale: string) =>
    request<User>('/me/locale', { method: 'PATCH', body: JSON.stringify({ locale }) }),

  // 元数据
  system: () => request<SystemInfo>('/system'),
  ocrProviders: () => request<OcrProviders>('/ocr/providers'),
  summary: (yearMonth?: string) => request<Summary>(`/summary${qs({ year_month: yearMonth })}`),

  // 账户
  accounts: (includeArchived = false) =>
    request<Account[]>(`/accounts${qs({ include_archived: includeArchived })}`),
  createAccount: (body: AccountInput) =>
    request<Account>('/accounts', { method: 'POST', body: JSON.stringify(body) }),
  updateAccount: (id: number, body: Partial<AccountInput>) =>
    request<Account>(`/accounts/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteAccount: (id: number) => request<void>(`/accounts/${id}`, { method: 'DELETE' }),
  reconcile: (id: number, body: { date: string; actual_balance: number; note?: string }) =>
    request<ReconcileResult>(`/accounts/${id}/reconcile`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  // 类目
  categories: (locale?: string, type?: 'expense' | 'income') =>
    request<CategoryNode[]>(`/categories${qs({ locale, type })}`),
  createCategory: (body: {
    parent_id?: number | null
    type: 'expense' | 'income'
    icon?: string | null
    color?: string | null
    names: Record<string, string>
  }) => request<CategoryNode>('/categories', { method: 'POST', body: JSON.stringify(body) }),
  updateCategory: (
    id: number,
    body: {
      icon?: string | null
      color?: string | null
      names?: Record<string, string>
      is_hidden?: boolean
    },
  ) => request<CategoryNode>(`/categories/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteCategory: (id: number) => request<void>(`/categories/${id}`, { method: 'DELETE' }),

  // 交易
  transactions: (filters: TransactionFilters = {}) =>
    request<TransactionPage>(`/transactions${qs({ ...filters })}`),
  createTransaction: (body: TransactionInput) =>
    request<Transaction>('/transactions', { method: 'POST', body: JSON.stringify(body) }),
  updateTransaction: (id: number, body: Partial<TransactionInput>) =>
    request<Transaction>(`/transactions/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteTransaction: (id: number) => request<void>(`/transactions/${id}`, { method: 'DELETE' }),
  restoreTransaction: (id: number) =>
    request<Transaction>(`/transactions/${id}/restore`, { method: 'POST' }),
  createTransfer: (body: TransferInput) =>
    request<Transaction[]>('/transactions/transfer', { method: 'POST', body: JSON.stringify(body) }),
  merchantSuggestions: (q: string) => request<string[]>(`/transactions/merchants${qs({ q })}`),
  suggestCategory: (merchant: string) =>
    request<{ category_id: number | null; confidence: number }>(
      `/transactions/suggest-category${qs({ merchant })}`,
    ),

  // 导入
  importBatches: (status?: BatchStatus) => request<ImportBatch[]>(`/imports${qs({ status })}`),
  importText: (body: {
    account_id: number
    text: string
    statement_month?: string | null
    batch_id?: number | null
  }) => request<BatchDetail>('/imports/text', { method: 'POST', body: JSON.stringify(body) }),
  importBatch: (id: number) => request<BatchDetail>(`/imports/${id}`),
  discardBatch: (id: number) => request<void>(`/imports/${id}`, { method: 'DELETE' }),
  revertBatch: (id: number) => request<BatchActionResult>(`/imports/${id}/revert`, { method: 'POST' }),
  removeBatchOverlaps: (id: number) =>
    request<BatchActionResult>(`/imports/${id}/remove-overlaps`, { method: 'POST' }),
  updateStagedRow: (batchId: number, rowId: number, body: StagedRowUpdate) =>
    request<StagedRowPatch>(`/imports/${batchId}/rows/${rowId}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  expandMerged: (batchId: number, rowId: number) =>
    request<StagedRow[]>(`/imports/${batchId}/rows/${rowId}/expand`, { method: 'POST' }),
  restoreExcluded: (batchId: number, rowId: number) =>
    request<StagedRow>(`/imports/${batchId}/rows/${rowId}/restore`, { method: 'POST' }),
  bulkUpdate: (
    batchId: number,
    body: { row_ids: number[]; category_id?: number; account_id?: number; is_selected?: boolean },
  ) => request<StagedRow[]>(`/imports/${batchId}/bulk`, { method: 'POST', body: JSON.stringify(body) }),
  confirmBatch: (id: number) => request<ConfirmResult>(`/imports/${id}/confirm`, { method: 'POST' }),
  csvPreview: (files: File[]) => {
    const form = new FormData()
    for (const f of files) form.append('files', f, f.name)
    return upload<CsvPreview>('/imports/csv/preview', form)
  },
  importCsv: (files: File[], accountId: number, mapping?: ColumnMapping | null, batchId?: number | null) => {
    const form = new FormData()
    for (const f of files) form.append('files', f, f.name)
    form.append('account_id', String(accountId))
    if (mapping) form.append('mapping', JSON.stringify(mapping))
    if (batchId) form.append('batch_id', String(batchId))
    return upload<BatchDetail>('/imports/csv', form)
  },

  // 规则
  rules: () => request<Rule[]>('/rules'),
  createRule: (body: {
    match_type: MatchType
    pattern: string
    category_id: number
    account_id?: number | null
    priority?: number
  }) => request<Rule>('/rules', { method: 'POST', body: JSON.stringify(body) }),
  updateRule: (
    id: number,
    body: Partial<{
      match_type: MatchType
      pattern: string
      category_id: number
      priority: number
      enabled: boolean
    }>,
  ) => request<Rule>(`/rules/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteRule: (id: number) => request<void>(`/rules/${id}`, { method: 'DELETE' }),

  // 报表 / 导出 / 备份
  reportOverview: (yearMonth: string, f: ReportFilters = {}) =>
    request<ReportOverview>(`/reports/overview${qs({ year_month: yearMonth, ...f })}`),
  reportTrend: (end: string, months: number, f: ReportFilters = {}) =>
    request<{ months: TrendMonth[] }>(`/reports/trend${qs({ end, months, ...f })}`),
  reportDaily: (yearMonth: string, f: ReportFilters = {}) =>
    request<DailyReport>(`/reports/daily${qs({ year_month: yearMonth, ...f })}`),
  reportLargeExpenses: (yearMonth: string, f: ReportFilters = {}, limit = 8) =>
    request<{ items: LargeExpense[] }>(`/reports/large-expenses${qs({ year_month: yearMonth, limit, ...f })}`),
  setExcludeFromAnalysis: (id: number, value: boolean) =>
    request<Transaction>(`/transactions/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ exclude_from_analysis: value }),
    }),
  convertToTransfer: (id: number, counterpartAccountId: number) =>
    request<Transaction[]>(`/transactions/${id}/to-transfer`, {
      method: 'POST',
      body: JSON.stringify({ counterpart_account_id: counterpartAccountId }),
    }),
  /** 导出走浏览器原生下载（带 Cookie），所以只给 URL 不发请求 */
  exportUrl: (f: TransactionFilters = {}) => `/api/transactions/export.csv${qs({ ...f })}`,
  backupUrl: '/api/backup',
}
