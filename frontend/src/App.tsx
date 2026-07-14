import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Navigate, Route, Routes } from 'react-router-dom'

import { api } from './api/client'
import { ApiError } from './api/types'
import { BoardPage } from './pages/BoardPage'
import { LoginPage } from './pages/LoginPage'
import { ProjectsPage } from './pages/ProjectsPage'

export function App() {
  const queryClient = useQueryClient()

  const me = useQuery({
    queryKey: ['me'],
    queryFn: api.me,
    retry: (_count, error) => !(error instanceof ApiError && error.status === 401),
  })

  const logout = useMutation({
    mutationFn: api.logout,
    onSuccess: () => queryClient.clear(),
  })

  if (me.isLoading) {
    return <div className="state state--loading">Loading…</div>
  }

  if (me.isError) {
    return <LoginPage />
  }

  return (
    <>
      <nav className="nav">
        <span className="nav__brand">ProjectBoard</span>
        <span className="nav__user">{me.data?.display_name}</span>
        <button className="btn btn--small" onClick={() => logout.mutate()}>
          Sign out
        </button>
      </nav>

      <Routes>
        <Route path="/" element={<ProjectsPage />} />
        <Route path="/projects/:projectId" element={<BoardPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </>
  )
}
