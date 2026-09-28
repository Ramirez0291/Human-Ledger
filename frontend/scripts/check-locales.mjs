/* Fails if any locale's keys differ from zh-CN. */

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
    console.error(`✗ ${file}: missing _meta.locale or _meta.nativeName`)
    process.exit(1)
  }
  if (json._meta.locale !== locale) {
    console.error(`✗ ${file}: _meta.locale "${json._meta.locale}" does not match file name`)
    process.exit(1)
  }
  bundles.set(locale, flatten(json))
}

if (!bundles.has(BASE)) {
  console.error(`✗ missing base locale ${BASE}.json`)
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
    for (const k of missing) console.error(`    missing: ${k}`)
    for (const k of extra) console.error(`    extra: ${k}`)
  } else {
    console.log(`✓ ${locale}  (${keys.size} keys)`)
  }
}

if (failed) {
  console.error('\nLocale keys differ. Fix them before building.')
  process.exit(1)
}

console.log(`\n✓ ${bundles.size} locales consistent, ${baseKeys.size} keys.`)
