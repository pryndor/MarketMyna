// Checks every translation against English (src/i18n/locales/en): same
// namespaces, same keys, same list lengths, same {{placeholders}} and <tags>.
// Plural keys (name_one, name_few, ...) count as one key "name"; each
// language may use the plural forms its grammar needs.
// Run: npm run check:i18n   (exits 1 and lists problems if any)
import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

// fileURLToPath, not URL.pathname: Windows drive letters and spaces in the path
const root = fileURLToPath(new URL('../src/i18n/locales/', import.meta.url))
const PLURAL = /_(zero|one|two|few|many|other)$/

function flatten(value, prefix, out) {
  if (Array.isArray(value)) {
    out.set(prefix, { list: value.length })
    value.forEach((v, i) => flatten(v, `${prefix}[${i}]`, out))
  } else if (value && typeof value === 'object') {
    for (const [k, v] of Object.entries(value)) flatten(v, prefix ? `${prefix}.${k.replace(PLURAL, '')}` : k.replace(PLURAL, ''), out)
  } else {
    const marks = new Set([...String(value).matchAll(/\{\{\s*(\w+)\s*\}\}|<\/?(\w+)\s*\/?>/g)].map((m) => m[1] ?? `<${m[2]}>`))
    const prev = out.get(prefix)
    // Plural forms of one key may differ (Arabic "zero" drops the number): keep the union.
    out.set(prefix, { marks: new Set([...(prev?.marks ?? []), ...marks]) })
  }
  return out
}

const load = (lng, ns) => flatten(JSON.parse(readFileSync(join(root, lng, ns), 'utf8')), '', new Map())

const languages = readdirSync(root).filter((d) => d !== 'en')
const namespaces = readdirSync(join(root, 'en'))
const problems = []

for (const ns of namespaces) {
  const en = load('en', ns)
  for (const lng of languages) {
    let other
    try {
      other = load(lng, ns)
    } catch (e) {
      problems.push(`${lng}/${ns}: ${e.code === 'ENOENT' ? 'missing file' : e.message}`)
      continue
    }
    for (const [key, ref] of en) {
      const got = other.get(key)
      if (!got) problems.push(`${lng}/${ns}: missing ${key}`)
      else if ('list' in ref && got.list !== ref.list) problems.push(`${lng}/${ns}: ${key} has ${got.list} items, English has ${ref.list}`)
      else if ('marks' in ref) {
        for (const m of ref.marks) if (!got.marks.has(m)) problems.push(`${lng}/${ns}: ${key} lacks ${m}`)
      }
    }
    for (const key of other.keys()) if (!en.has(key)) problems.push(`${lng}/${ns}: extra key ${key}`)
  }
}

if (problems.length) {
  console.error(problems.join('\n'))
  process.exit(1)
}
console.log(`i18n: ${languages.length} languages × ${namespaces.length} namespaces match English`)
