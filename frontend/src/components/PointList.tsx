/** A titled bullet list in an AI review (strengths, concerns, actions); nothing when empty. */
export default function PointList({ title, tone, items }: { title: string; tone: string; items: string[] }) {
  if (!items.length) return null
  return (
    <div>
      <div className={`mb-1.5 text-xs font-semibold ${tone}`}>{title}</div>
      <ul className="list-disc space-y-1 ps-4 text-sm text-fg/90">
        {items.map((p) => <li key={p}>{p}</li>)}
      </ul>
    </div>
  )
}
