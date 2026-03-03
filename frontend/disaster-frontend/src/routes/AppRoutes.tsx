import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import AppLayout from '../layout/AppLayout'
import RequireRole from '../auth/RequireRole'

import Login from '../pages/Login'
import DistrictDashboard from '../pages/DistrictDashboard'
import StateDashboard from '../pages/StateDashboard'
import NationalDashboard from '../pages/NationalDashboard'
import AdminDashboard from '../pages/AdminDashboard'
import DistrictRequest from '../dashboards/district/DistrictRequest'
import StateRequests from '../dashboards/state/StateRequests'
import NationalRequests from '../dashboards/national/NationalRequests'
import AdminScenarioRunDetails from '../dashboards/admin/AdminScenarioRunDetails'
export default function AppRoutes() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />

        <Route element={<AppLayout />}>
          <Route
            path="/district"
            element={
              <RequireRole allowed={['district']}>
                <DistrictDashboard />
              </RequireRole>
            }
          />
          <Route
            path="/state"
            element={
              <RequireRole allowed={['state']}>
                <StateDashboard />
              </RequireRole>
            }
          />
          <Route
            path="/national"
            element={
              <RequireRole allowed={['national']}>
                <NationalDashboard />
              </RequireRole>
            }
          />
          <Route
  path="/state/requests"
  element={
    <RequireRole allowed={['state']}>
      <StateRequests />
    </RequireRole>
  }
/>

          <Route
  path="/district/request"
  element={
    <RequireRole allowed={['district']}>
      <DistrictRequest />
    </RequireRole>
  }
/>
<Route
  path="/national/requests"
  element={
    <RequireRole allowed={['national']}>
      <NationalRequests />
    </RequireRole>
  }
/>


          <Route
            path="/admin"
            element={
              <RequireRole allowed={['admin']}>
                <AdminDashboard initialAdminView="system" />
              </RequireRole>
            }
          />
          <Route
            path="/admin/system"
            element={
              <RequireRole allowed={['admin']}>
                <AdminDashboard initialAdminView="system" />
              </RequireRole>
            }
          />
          <Route
            path="/admin/scenarios"
            element={
              <RequireRole allowed={['admin']}>
                <AdminDashboard initialAdminView="scenarios" />
              </RequireRole>
            }
          />
          <Route
            path="/admin/scenarios/:scenarioId/runs/:runId"
            element={
              <RequireRole allowed={['admin']}>
                <AdminScenarioRunDetails />
              </RequireRole>
            }
          />
        </Route>

        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
