import AdminOverview from '../dashboards/admin/AdminOverview'

type Props = {
  initialAdminView?: 'system' | 'scenarios'
}

export default function AdminDashboard({ initialAdminView }: Props) {
  return <AdminOverview initialAdminView={initialAdminView} />
}
