/** Export one or more tables as CSV, Excel (.xlsx) or PDF, entirely in the browser.
 * The xlsx and pdf libraries load only when an export is requested. */

import { saveBlob } from './files'

type ExportKind = 'text' | 'number' | 'pct' | 'money' | 'date'

export interface ExportColumn {
  key: string
  label: string
  kind?: ExportKind
  /** Decimals for PDF display (raw numbers go to CSV / Excel). */
  digits?: number
}

export interface ExportTable {
  title: string
  columns: ExportColumn[]
  rows: ReadonlyArray<object>
  note?: string
  /** Leave this table out of PDFs (long raw series that only make sense in a spreadsheet). */
  pdf?: boolean
}

export type ExportFormat = 'csv' | 'xlsx' | 'pdf'

function stamp(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

function safeName(base: string): string {
  return `${base.replace(/[^\w\- ]+/g, '').trim().replace(/\s+/g, '-').toLowerCase() || 'export'}-${stamp()}`
}

const cell = (row: object, key: string): unknown => (row as Record<string, unknown>)[key]

function raw(v: unknown): string | number | boolean | null {
  if (v == null) return null
  if (typeof v === 'number') return Number.isFinite(v) ? v : null
  if (typeof v === 'boolean') return v
  if (Array.isArray(v)) return v.join(', ')
  return String(v)
}

/** PDF text for a value; a row's `_kind` overrides the column kind for numbers (mixed-unit tables). */
function display(v: unknown, col: ExportColumn, row?: object): string {
  const r = raw(v)
  if (r == null) return '-'
  if (typeof r !== 'number') return String(r)
  const kind = ((row as { _kind?: ExportKind } | undefined)?._kind) ?? col.kind
  if (kind === 'money') return r.toLocaleString('en-US', { notation: 'compact', maximumFractionDigits: 2 })
  const digits = col.digits ?? (kind === 'pct' ? 1 : Math.abs(r) >= 1000 ? 0 : 2)
  const s = r.toLocaleString('en-IN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
  return kind === 'pct' ? `${s}%` : s
}


function csvCell(v: unknown): string {
  const r = raw(v)
  if (r == null) return ''
  const s = String(r)
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
}

function toCsv(tables: ExportTable[]): string {
  const parts: string[] = []
  for (const t of tables) {
    if (tables.length > 1) parts.push(csvCell(t.title))
    parts.push(t.columns.map((c) => csvCell(c.label)).join(','))
    for (const row of t.rows) parts.push(t.columns.map((c) => csvCell(cell(row, c.key))).join(','))
    if (t.note) parts.push(csvCell(t.note))
    parts.push('')
  }
  return parts.join('\r\n')
}

/** jsPDF's built-in fonts are Latin-1 only. */
function latin(s: string): string {
  return s
    .replace(/₹/g, 'Rs ')
    .replace(/[–—−]/g, '-')
    .replace(/[‘’]/g, "'")
    .replace(/[“”]/g, '"')
    .replace(/·/g, '|')
    .replace(/[^\x20-\x7e\xa0-\xff\n]/g, '?')
}

export async function exportTables(format: ExportFormat, title: string, tables: ExportTable[], subtitle?: string): Promise<void> {
  const base = safeName(title)
  const usable = tables.filter((t) => t.columns.length)
  if (format === 'csv') {
    saveBlob(new Blob(['﻿', toCsv(usable)], { type: 'text/csv;charset=utf-8' }), `${base}.csv`)
    return
  }
  if (format === 'xlsx') {
    const { default: writeXlsxFile } = await import('write-excel-file/browser')
    const used = new Set<string>()
    const sheets = usable.map((t) => {
      let name = t.title.replace(/[[\]:*?/\\]/g, ' ').slice(0, 31).trim() || 'Sheet'
      for (let i = 2; used.has(name); i++) name = `${name.slice(0, 28)} ${i}`
      used.add(name)
      const header = t.columns.map((c) => ({ value: c.label, fontWeight: 'bold' as const }))
      const body = t.rows.map((row) => t.columns.map((c) => {
        const v = raw(cell(row, c.key))
        return v == null ? null : { value: v }
      }))
      const extra = t.note ? [[], [{ value: t.note }]] : []
      return {
        sheet: name,
        data: [header, ...body, ...extra],
        columns: t.columns.map((c) => ({ width: Math.min(Math.max(c.label.length + 2, c.kind === 'text' || !c.kind ? 18 : 12), 48) })),
        stickyRowsCount: 1,
      }
    })
    const blob = await writeXlsxFile(sheets as Parameters<typeof writeXlsxFile>[0]).toBlob()
    saveBlob(blob, `${base}.xlsx`)
    return
  }
  const [{ jsPDF }, { default: autoTable }] = await Promise.all([import('jspdf'), import('jspdf-autotable')])
  const doc = new jsPDF({ orientation: 'landscape', unit: 'pt', format: 'a4' })
  const margin = 36
  doc.setFontSize(15)
  doc.text(latin(title), margin, margin + 4)
  doc.setFontSize(9)
  doc.setTextColor(110)
  doc.text(latin(`${subtitle ? `${subtitle}  |  ` : ''}Generated ${new Date().toLocaleString('en-IN')} by MarketMyna`), margin, margin + 20)
  let y = margin + 36
  for (const t of usable.filter((x) => x.pdf !== false)) {
    doc.setFontSize(11)
    doc.setTextColor(20)
    if (y > doc.internal.pageSize.getHeight() - 90) {
      doc.addPage()
      y = margin
    }
    doc.text(latin(t.title), margin, y)
    autoTable(doc, {
      startY: y + 6,
      margin: { left: margin, right: margin },
      head: [t.columns.map((c) => latin(c.label))],
      body: t.rows.map((row) => t.columns.map((c) => latin(display(cell(row, c.key), c, row)))),
      styles: { fontSize: 8, cellPadding: 3 },
      headStyles: { fillColor: [55, 75, 160] },
      columnStyles: Object.fromEntries(t.columns.map((c, i) => [i, { halign: c.kind && c.kind !== 'text' && c.kind !== 'date' ? 'right' : 'left' }])),
    })
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    y = (doc as any).lastAutoTable.finalY + 14
    if (t.note) {
      doc.setFontSize(8)
      doc.setTextColor(110)
      const lines = doc.splitTextToSize(latin(t.note), doc.internal.pageSize.getWidth() - margin * 2)
      doc.text(lines, margin, y)
      y += lines.length * 10 + 10
    }
    y += 10
  }
  const pages = doc.getNumberOfPages()
  for (let i = 1; i <= pages; i++) {
    doc.setPage(i)
    doc.setFontSize(7)
    doc.setTextColor(140)
    doc.text(`MarketMyna | Data may be delayed | Not investment advice | Page ${i} of ${pages}`, margin, doc.internal.pageSize.getHeight() - 16)
  }
  saveBlob(doc.output('blob'), `${base}.pdf`)
}
