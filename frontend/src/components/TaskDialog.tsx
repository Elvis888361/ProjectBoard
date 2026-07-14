import { useEffect, useState } from 'react'

import { STATUSES, type Task, type TaskStatus, type User } from '../api/types'

interface Props {
  task: Task
  users: User[]
  onSave: (fields: Record<string, unknown>) => void
  onDelete: () => void
  onClose: () => void
  saving: boolean
}

export function TaskDialog({ task, users, onSave, onDelete, onClose, saving }: Props) {
  const [title, setTitle] = useState(task.title)
  const [description, setDescription] = useState(task.description)
  const [status, setStatus] = useState<TaskStatus>(task.status)
  const [assignee, setAssignee] = useState(task.assignee_id ?? '')
  const [due, setDue] = useState(task.due_date ?? '')

  // If someone else edits this task while the dialog is open, the SSE event updates the
  // cache and this prop changes underneath us. Re-sync -- otherwise the user saves a
  // form built from a version that no longer exists and eats a 409 they can't act on.
  useEffect(() => {
    setTitle(task.title)
    setDescription(task.description)
    setStatus(task.status)
    setAssignee(task.assignee_id ?? '')
    setDue(task.due_date ?? '')
  }, [task])

  useEffect(() => {
    const onEsc = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onEsc)
    return () => window.removeEventListener('keydown', onEsc)
  }, [onClose])

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = title.trim()
    if (!trimmed) return

    // Send only what changed. That's what makes this a PATCH rather than a PUT, and it
    // narrows the blast radius of a conflict: two people editing different fields of
    // the same task don't need to fight, even though they share a version number.
    const fields: Record<string, unknown> = {}
    if (trimmed !== task.title) fields.title = trimmed
    if (description !== task.description) fields.description = description
    if (status !== task.status) fields.status = status

    const nextAssignee = assignee || null
    if (nextAssignee !== task.assignee_id) {
      if (nextAssignee) fields.assignee_id = nextAssignee
      else fields.clear_assignee = true
    }

    const nextDue = due || null
    if (nextDue !== task.due_date) {
      if (nextDue) fields.due_date = nextDue
      else fields.clear_due_date = true
    }

    if (Object.keys(fields).length === 0) {
      onClose()
      return
    }
    onSave(fields)
  }

  return (
    <div className="backdrop" onClick={onClose} role="presentation">
      <div
        className="dialog"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Edit task"
      >
        <form onSubmit={submit}>
          <label>
            Title
            <input value={title} onChange={(e) => setTitle(e.target.value)} required maxLength={200} autoFocus />
          </label>

          <label>
            Description
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={4}
              maxLength={5000}
            />
          </label>

          <div className="dialog__row">
            <label>
              {/* Also the keyboard path for moving a task: drag-and-drop is mouse-only,
                  so this select is how a keyboard user changes a column. */}
              Status
              <select value={status} onChange={(e) => setStatus(e.target.value as TaskStatus)}>
                {STATUSES.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.label}
                  </option>
                ))}
              </select>
            </label>

            <label>
              Assignee
              <select value={assignee} onChange={(e) => setAssignee(e.target.value)}>
                <option value="">Unassigned</option>
                {users.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.display_name}
                  </option>
                ))}
              </select>
            </label>

            <label>
              Due date
              <input type="date" value={due} onChange={(e) => setDue(e.target.value)} />
            </label>
          </div>

          <footer className="dialog__actions">
            <button type="button" className="btn btn--danger" onClick={onDelete}>
              Delete
            </button>
            <div className="spacer" />
            <button type="button" className="btn" onClick={onClose}>
              Cancel
            </button>
            <button type="submit" className="btn btn--primary" disabled={saving}>
              {saving ? 'Saving…' : 'Save'}
            </button>
          </footer>
        </form>
      </div>
    </div>
  )
}
