import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import { ApiError, type Task, type TaskStatus } from '../api/types'

export const taskKeys = {
  list: (projectId: string) => ['tasks', projectId] as const,
}

/**
 * State management, and why there is no Redux/Zustand store in this app.
 *
 * Nearly all the state on this screen is a cached copy of something the server owns.
 * That is precisely what TanStack Query is for: it gives caching, request dedup,
 * background refetch, and -- the reason it actually earns its place here -- optimistic
 * mutation with automatic rollback, which I would otherwise have hand-rolled.
 *
 * Putting server data in Redux would mean re-implementing all of that and then keeping
 * a second copy of the truth in sync with the SSE stream. The genuinely client-side
 * state left over (which dialog is open, what's in the filter box) is small, local, and
 * lives in useState. A global store here would be ceremony, not architecture.
 */
export function useTasks(projectId: string, filters: { search?: string; assignee_id?: string }) {
  return useQuery({
    queryKey: taskKeys.list(projectId),
    queryFn: () => api.tasks(projectId, filters),
    // The SSE stream is what keeps this fresh, so polling would be redundant work.
    // If the stream dies, the browser reconnects and replays -- we don't need a
    // refetch interval as a safety net for that.
    refetchOnWindowFocus: false,
    staleTime: Infinity,
  })
}

/** Sort within a column exactly the way the server's `ORDER BY position, id` does.
 *  Positions are lexicographic strings -- comparing them numerically would be wrong. */
export function tasksInColumn(tasks: Task[], status: TaskStatus): Task[] {
  return tasks
    .filter((t) => t.status === status)
    .sort((a, b) => (a.position < b.position ? -1 : a.position > b.position ? 1 : a.id < b.id ? -1 : 1))
}

interface MoveArgs {
  task: Task
  toStatus: TaskStatus
  /** Task to land immediately after (null = top of column). */
  beforeId: string | null
  /** Task to land immediately before (null = bottom of column). */
  afterId: string | null
  /** Where to draw the card while the request is in flight. */
  optimisticPosition: string
}

export function useMoveTask(projectId: string, onConflict: (message: string) => void) {
  const queryClient = useQueryClient()
  const key = taskKeys.list(projectId)

  return useMutation({
    mutationFn: ({ task, toStatus, beforeId, afterId }: MoveArgs) =>
      api.moveTask(task.id, task.version, toStatus, beforeId, afterId),

    onMutate: async ({ task, toStatus, optimisticPosition }: MoveArgs) => {
      // Cancel in-flight board fetches first. Without this, a refetch that was already
      // on the wire can land after our optimistic write and stomp it -- the card
      // visibly jumps back. This is the documented first step of the pattern and it is
      // not optional.
      await queryClient.cancelQueries({ queryKey: key })

      const previous = queryClient.getQueryData<Task[]>(key)

      queryClient.setQueryData<Task[]>(key, (tasks) =>
        tasks?.map((t) =>
          t.id === task.id ? { ...t, status: toStatus, position: optimisticPosition } : t,
        ),
      )

      return { previous }
    },

    onError: (error, _vars, context) => {
      // Roll the board back to exactly what it looked like before the drag. The user
      // sees the card return to where it was, which is the truth.
      if (context?.previous) queryClient.setQueryData(key, context.previous)

      if (error instanceof ApiError && error.code === 'version_conflict') {
        // The 409 carries the current server state, so we can repair the one card that
        // conflicted instead of refetching the whole board.
        const current = error.currentTask
        if (current) {
          queryClient.setQueryData<Task[]>(key, (tasks) =>
            tasks?.map((t) => (t.id === current.id ? current : t)),
          )
        }
        onConflict(error.message)
      } else if (error instanceof ApiError) {
        onConflict(error.message)
      }
    },

    onSuccess: (serverTask) => {
      // Replace the optimistic guess with the server's authoritative row -- crucially,
      // its `position` (which the server computed) and its new `version`. Bumping the
      // cached version here also means the echo of our own change arriving over SSE a
      // moment later is dropped by the version guard instead of being re-applied.
      queryClient.setQueryData<Task[]>(key, (tasks) =>
        tasks?.map((t) => (t.id === serverTask.id ? serverTask : t)),
      )
    },
  })
}

export function useCreateTask(projectId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (task: Partial<Task>) => api.createTask(projectId, task),
    // No optimistic insert: the server assigns the id and the position, and inventing a
    // fake id client-side buys a few hundred milliseconds in exchange for a whole class
    // of reconciliation bugs. The card appears when the server says it exists.
    onSuccess: (created) => {
      queryClient.setQueryData<Task[]>(taskKeys.list(projectId), (tasks) =>
        tasks ? [...tasks.filter((t) => t.id !== created.id), created] : [created],
      )
    },
  })
}

export function useUpdateTask(projectId: string, onConflict: (message: string) => void) {
  const queryClient = useQueryClient()
  const key = taskKeys.list(projectId)

  return useMutation({
    mutationFn: ({ task, fields }: { task: Task; fields: Record<string, unknown> }) =>
      api.updateTask(task.id, task.version, fields),

    onSuccess: (updated) => {
      queryClient.setQueryData<Task[]>(key, (tasks) =>
        tasks?.map((t) => (t.id === updated.id ? updated : t)),
      )
    },

    onError: (error) => {
      if (error instanceof ApiError) {
        const current = error.currentTask
        if (current) {
          queryClient.setQueryData<Task[]>(key, (tasks) =>
            tasks?.map((t) => (t.id === current.id ? current : t)),
          )
        }
        onConflict(error.message)
      }
    },
  })
}

export function useDeleteTask(projectId: string) {
  const queryClient = useQueryClient()
  const key = taskKeys.list(projectId)

  return useMutation({
    mutationFn: (task: Task) => api.deleteTask(task.id),
    onMutate: async (task: Task) => {
      await queryClient.cancelQueries({ queryKey: key })
      const previous = queryClient.getQueryData<Task[]>(key)
      queryClient.setQueryData<Task[]>(key, (tasks) => tasks?.filter((t) => t.id !== task.id))
      return { previous }
    },
    onError: (_e, _task, context) => {
      if (context?.previous) queryClient.setQueryData(key, context.previous)
    },
  })
}
