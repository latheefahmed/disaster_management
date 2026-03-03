import { Navigate } from 'react-router-dom'
import { useAuth, UserRole } from './AuthContext'
import React from 'react'

export default function RequireRole({
  allowed,
  children
}: {
  allowed: UserRole[]
  children: React.ReactNode
}) {
  const { user, isReady } = useAuth()

  if (!isReady) return null

  if (!user) return <Navigate to="/login" replace />

  if (!allowed.includes(user.role))
    return <Navigate to="/login" replace />

  return <>{children}</>
}
