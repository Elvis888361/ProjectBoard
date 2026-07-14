import {
  ApiError,
  type ApiErrorBody,
  type ActivityEntry,
  type Project,
  type Task,
  type TaskStatus,
  type User,
} from './types'

const BASE = '/api/v1'

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    // The session cookie is httpOnly, so there is no token for us to attach by hand --
    // we just have to tell fetch to send cookies. Same-origin in dev (Vite proxy) and
    // in prod (nginx), so this is `same-origin`, not `include`.
    credentials: 'same-origin',
    headers: {
      'Content-Type': 'application/json',
      ...init.headers,
    },
  })

  if (res.status === 204) return undefined as T

  const body = await res.json().catch(() => null)

  if (!res.ok) {
    const err = (body as ApiErrorBody | null)?.error
    throw new ApiError(
      res.status,
      err?.code ?? 'unknown',
      err?.message ?? `Request failed (${res.status})`,
      err?.details,
    )
  }

  return body as T
}

export const api = {
  register: (email: string, password: string, displayName: string) =>
    request<User>('/auth/register', {
      method: 'POST',
      body: JSON.stringify({ email, password, display_name: displayName }),
    }),

  login: (email: string, password: string) =>
    request<User>('/auth/login', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    }),

  logout: () => request<void>('/auth/logout', { method: 'POST' }),

  me: () => request<User>('/auth/me'),

  users: () => request<User[]>('/users'),

  projects: () => request<Project[]>('/projects'),

  project: (id: string) => request<Project>(`/projects/${id}`),

  createProject: (name: string, description: string) =>
    request<Project>('/projects', {
      method: 'POST',
      body: JSON.stringify({ name, description }),
    }),

  deleteProject: (id: string) => request<void>(`/projects/${id}`, { method: 'DELETE' }),

  tasks: (projectId: string, filters: { search?: string; assignee_id?: string } = {}) => {
    const qs = new URLSearchParams()
    if (filters.search) qs.set('search', filters.search)
    if (filters.assignee_id) qs.set('assignee_id', filters.assignee_id)
    const suffix = qs.toString() ? `?${qs}` : ''
    return request<Task[]>(`/projects/${projectId}/tasks${suffix}`)
  },

  createTask: (projectId: string, task: Partial<Task>) =>
    request<Task>(`/projects/${projectId}/tasks`, {
      method: 'POST',
      body: JSON.stringify(task),
    }),

  updateTask: (taskId: string, version: number, fields: Record<string, unknown>) =>
    request<Task>(`/tasks/${taskId}`, {
      method: 'PATCH',
      body: JSON.stringify({ version, ...fields }),
    }),

  /**
   * Moves are relational: we name the neighbours, the server computes the position.
   * We never send a position value -- if two people drag into the same gap at once,
   * neither client picked the number, so there's nothing for them to disagree about.
   */
  moveTask: (
    taskId: string,
    version: number,
    status: TaskStatus,
    beforeId: string | null,
    afterId: string | null,
  ) =>
    request<Task>(`/tasks/${taskId}/move`, {
      method: 'POST',
      body: JSON.stringify({
        version,
        status,
        before_id: beforeId,
        after_id: afterId,
      }),
    }),

  deleteTask: (taskId: string) => request<void>(`/tasks/${taskId}`, { method: 'DELETE' }),

  activity: (projectId: string) =>
    request<ActivityEntry[]>(`/projects/${projectId}/activity`),
}
