/**
 * 词条一致性检查。
 *
 * 三种语言并行维护时，漏译是最容易发生也最难被发现的问题——界面上只会
 * 显示原始 key，不会报错。此脚本以 zh-CN 为基准，比对所有语言的 key 集合，
 * 有缺失或多余即以非零码退出。已接入 npm run build。
 *
 * 新增语言时无需修改此脚本。
 */

import { readFileSync, readdirSync } from 'node:fs'
import { join, dirname, basename } from 'node:path'
import { fileURLToPath } from 'node:url'

const localesDir = join(dirname(fileURLToPath(import.meta.url)), '..', 'src', 'i18n', 'locales')
const BASE = 'zh-CN'

function flatten(obj, prefix = '', out = new Set()) {
  for (const [k, v] of Object.entries(obj)) {
    if (k === '_meta') continue
    const path = prefix ? `${prefix}.${k}` : k
    if (v && typeof v === 'object' && !Array.isArray(v)) flatten(v, path, out)
    else out.add(path)
  }
  return out
}

const files = readdirSync(localesDir).filter((f) => f.endsWith('.json'))
const bundles = new Map()

for (const file of files) {
  const locale = basename(file, '.json')
  const json = JSON.parse(readFileSync(join(localesDir, file), 'utf8'))
  if (!json._meta?.locale || !json._meta?.nativeName) {
    console.error(`✗ ${file}: 缺少 _meta.locale 或 _meta.nativeName`)
    process.exit(1)
  }
  if (json._meta.locale !== locale) {
    console.error(`✗ ${file}: _meta.locale 为 "${json._meta.locale}"，与文件名不一致`)
    process.exit(1)
  }
  bundles.set(locale, flatten(json))
}

if (!bundles.has(BASE)) {
  console.error(`✗ 缺少基准语言文件 ${BASE}.json`)
  process.exit(1)
}

const baseKeys = bundles.get(BASE)
let failed = false

for (const [locale, keys] of bundles) {
  if (locale === BASE) continue
  const missing = [...baseKeys].filter((k) => !keys.has(k))
  const extra = [...keys].filter((k) => !baseKeys.has(k))

  if (missing.length || extra.length) {
    failed = true
    console.error(`✗ ${locale}`)
    for (const k of missing) console.error(`    缺少: ${k}`)
    for (const k of extra) console.error(`    多余: ${k}`)
  } else {
    console.log(`✓ ${locale}  (${keys.size} 条)`)
  }
}

if (failed) {
  console.error('\n词条不一致，请补齐后再构建。')
  process.exit(1)
}

console.log(`\n✓ ${bundles.size} 种语言词条一致，共 ${baseKeys.size} 条。`)
