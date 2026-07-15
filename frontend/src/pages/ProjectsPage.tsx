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
        <div>
          <h1>Projects</h1>
          <p className="page__subtitle">Pick a board, or start a new one.</p>
        </div>
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
          <p>Create your first board above and start adding tasks.</p>
        </div>
      )}

      {(projects.data?.length ?? 0) > 0 && (
        <div className="boards">
          {(projects.data ?? []).map((p) => (
            <Link key={p.id} to={`/projects/${p.id}`} className="board-card">
              <span className="board-card__cover" style={{ background: coverGradient(p.name) }}>
                <span className="board-card__initial">{p.name.trim()[0]?.toUpperCase() ?? '?'}</span>
              </span>
              <span className="board-card__body">
                <span className="board-card__name">{p.name}</span>
                <span className="board-card__count">
                  {p.task_count} {p.task_count === 1 ? 'task' : 'tasks'}
                </span>
              </span>
              <button
                className="board-card__delete"
                aria-label={`Delete ${p.name}`}
                onClick={(e) => {
                  e.preventDefault()
                  if (confirm(`Delete "${p.name}" and all its tasks?`)) remove.mutate(p.id)
                }}
              >
                Delete
              </button>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}

const COVERS = [
  ['#2563eb', '#7c3aed'],
  ['#0891b2', '#2563eb'],
  ['#059669', '#0891b2'],
  ['#d97706', '#db2777'],
  ['#db2777', '#7c3aed'],
  ['#475569', '#0f172a'],
]
function coverGradient(name: string): string {
  let hash = 0
  for (const ch of name) hash = (hash * 31 + ch.charCodeAt(0)) | 0
  const [a, b] = COVERS[Math.abs(hash) % COVERS.length]
  return `linear-gradient(135deg, ${a}, ${b})`
}
