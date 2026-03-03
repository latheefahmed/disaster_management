export default function Section({
  title,
  children,
}: {
  title: string
  children: React.ReactNode
}) {
  return (
    <section className="mb-6 rounded-2xl border border-slate-200/70 bg-white/80 p-4 shadow-sm backdrop-blur sm:p-5">
      <h3 className="mb-3 text-lg font-semibold tracking-tight text-slate-800">{title}</h3>
      {children}
    </section>
  )
}
