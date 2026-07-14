export type TaskStatus = 'todo' | 'in_progress' | 'done'

export const STATUSES: { id: TaskStatus; label: string }[] = [
  { id: 'todo', label: 'Todo' },
  { id: 'in_progress', label: 'In Progress' },
  { id: 'done', label: 'Done' },
]

export interface User {
  id: string
  email: string
  display_name: string
}

export interface Project {
  id: string
  name: string
  description: string
  created_by: string
  created_at: string
  task_count: number
}

export interface Task {
  id: string
  project_id: string
  title: string
  description: string
  status: TaskStatus
  assignee_id: string | null
  assignee_name: string | null
  due_date: string | null
  /** Fractional index. Compare as a string; never parse it. */
  position: string
  /** Sent with every mutation, and used to drop stale events. */
  version: number
  created_at: string
  updated_at: string
}

export interface ActivityEntry {
  id: number
  type: string
  task_id: string | null
  actor_name: string | null
  payload: Record<string, unknown>
  created_at: string
}

/** Every non-2xx response from the API. */
export interface ApiErrorBody {
  error: {
    code: string
    message: string
    details?: unknown
  }
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly details?: unknown,
  ) {
    super(message)
  }

  /** A 409 carries current server state, so the UI can reconcile without a refetch. */
  get currentTask(): Task | undefined {
    const details = this.details as { current?: Task } | undefined
    return details?.current
  }
}
