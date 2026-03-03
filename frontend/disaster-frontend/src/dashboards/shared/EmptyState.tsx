export default function EmptyState({ message }: { message: string }) {
  return (
    <div className="rounded-xl border bg-slate-50 p-6 text-slate-600">
      {message}
    </div>
  )
}
