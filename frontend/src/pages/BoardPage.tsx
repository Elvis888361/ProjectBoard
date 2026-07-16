import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { api } from '../api/client'
import type { Task } from '../api/types'
import { Board } from '../components/Board'
import { TaskDialog } from '../components/TaskDialog'
import { useProjectStream } from '../hooks/useProjectStream'
import { useCreateTask, useDeleteTask, useTasks, useUpdateTask } from '../hooks/useTasks'

export function BoardPage() {
  const { projectId = '' } = useParams()
  const [search, setSearch] = useState('')
  const [assignee, setAssignee] = useState('')
  const [openTaskId, setOpenTaskId] = useState<string | null>(null)
  const [newTitle, setNewTitle] = useState('')
  const [toast, setToast] = useState<string | null>(null)

  const notify = (message: string) => {
    setToast(message)
    window.setTimeout(() => setToast(null), 5000)
  }

  const streamStatus = useProjectStream(projectId)

  const project = useQuery({ queryKey: ['project', projectId], queryFn: () => api.project(projectId) })
  const users = useQuery({ queryKey: ['users'], queryFn: api.users })

  const tasksQuery = useTasks(projectId, {})

  const filtered = useMemo(() => {
    const all = tasksQuery.data ?? []
    const needle = search.trim().toLowerCase()
    return all.filter((t) => {
      if (assignee && t.assignee_id !== assignee) return false
      if (!needle) return true
      return (
        t.title.toLowerCase().includes(needle) || t.description.toLowerCase().includes(needle)
      )
    })
  }, [tasksQuery.data, search, assignee])

  const createTask = useCreateTask(projectId)
  const updateTask = useUpdateTask(projectId, notify)
  const deleteTask = useDeleteTask(projectId)

  const openTask = tasksQuery.data?.find((t) => t.id === openTaskId) ?? null

  const addTask = (e: React.FormEvent) => {
    e.preventDefault()
    const title = newTitle.trim()
    if (!title) return
    createTask.mutate({ title, status: 'todo' })
    setNewTitle('')
  }

  if (tasksQuery.isLoading || project.isLoading) {
    return <div className="state state--loading">Loading board…</div>
  }

  if (tasksQuery.isError || project.isError) {

    return (
      <div className="state state--error">
        <p>Couldn&apos;t load this board. It may have been deleted.</p>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'center', marginTop: 12 }}>
          <button className="btn" onClick={() => tasksQuery.refetch()}>
            Try again
          </button>
          <Link to="/" className="btn btn--primary">
            Back to projects
          </Link>
        </div>
      </div>
    )
  }

  return (
    <div className="page">
      <header className="page__header">
        <div>
          <Link to="/" className="back">
            ← Projects
          </Link>
          <h1>{project.data?.name}</h1>
        </div>

        <span className={`stream stream--${streamStatus}`} role="status">
          {streamStatus === 'live' ? 'Live' : 'Reconnecting…'}
        </span>
      </header>

      <div className="toolbar">
        <form onSubmit={addTask} className="toolbar__add">
          <input
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            placeholder="Add a task…"
            aria-label="New task title"
            maxLength={200}
          />
          <button className="btn btn--primary" disabled={!newTitle.trim() || createTask.isPending}>
            Add
          </button>
        </form>

        <input
          className="toolbar__search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search tasks…"
          aria-label="Search tasks"
          type="search"
        />

        <select
          value={assignee}
          onChange={(e) => setAssignee(e.target.value)}
          aria-label="Filter by assignee"
        >
          <option value="">Everyone</option>
          {(users.data ?? []).map((u) => (
            <option key={u.id} value={u.id}>
              {u.display_name}
            </option>
          ))}
        </select>
      </div>

      {(tasksQuery.data ?? []).length === 0 ? (
        <div className="state state--empty">
          <h2>This board is empty</h2>
          <p>Add your first task above to get started.</p>
        </div>
      ) : (
        <Board
          projectId={projectId}
          tasks={filtered}
          onOpenTask={(t: Task) => setOpenTaskId(t.id)}
          onConflict={notify}
        />
      )}

      {openTask && (
        <TaskDialog
          task={openTask}
          users={users.data ?? []}
          saving={updateTask.isPending}
          onSave={(fields) => {
            updateTask.mutate({ task: openTask, fields })
            setOpenTaskId(null)
          }}
          onDelete={() => {
            deleteTask.mutate(openTask)
            setOpenTaskId(null)
          }}
          onClose={() => setOpenTaskId(null)}
        />
      )}

      {toast && (
        <div className="toast" role="alert">
          {toast}
        </div>
      )}
    </div>
  )
}
