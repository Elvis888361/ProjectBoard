import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'

import { api } from '../api/client'

export function ProjectsPage() {
  const queryClient = useQueryClient()
  const [name, setName] = useState('')

  const projects = useQuery({ queryKey: ['projects'], queryFn: api.projects })

  const create = useMutation({
    mutationFn: () => api.createProject(name.trim(), ''),
    onSuccess: () => {
      setName('')
      queryClient.invalidateQueries({ queryKey: ['projects'] })
    },
  })

  const remove = useMutation({
    mutationFn: (id: string) => api.deleteProject(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['projects'] }),
  })

  return (
    <div className="page">
      <header className="page__header">
        <h1>Projects</h1>
      </header>

      <form
        className="toolbar"
        onSubmit={(e) => {
          e.preventDefault()
          if (name.trim()) create.mutate()
        }}
      >
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="New project name…"
          aria-label="New project name"
          maxLength={120}
        />
        <button className="btn btn--primary" disabled={!name.trim() || create.isPending}>
          Create
        </button>
      </form>

      {projects.isLoading && <div className="state state--loading">Loading projects…</div>}

      {projects.isError && (
        <div className="state state--error">
          <p>Couldn&apos;t load your projects.</p>
          <button className="btn" onClick={() => projects.refetch()}>
            Try again
          </button>
        </div>
      )}

      {projects.data?.length === 0 && (
        <div className="state state--empty">
          <h2>No projects yet</h2>
          <p>Create one above and start adding tasks.</p>
        </div>
      )}

      <ul className="projects">
        {(projects.data ?? []).map((p) => (
          <li key={p.id} className="projects__item">
            <Link to={`/projects/${p.id}`}>
              <h2>{p.name}</h2>
              <span>
                {p.task_count} {p.task_count === 1 ? 'task' : 'tasks'}
              </span>
            </Link>
            <button
              className="btn btn--danger btn--small"
              aria-label={`Delete ${p.name}`}
              onClick={() => {
                if (confirm(`Delete "${p.name}" and all its tasks?`)) remove.mutate(p.id)
              }}
            >
              Delete
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
