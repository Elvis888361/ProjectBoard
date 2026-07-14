import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import { ApiError, type Task, type TaskStatus } from '../api/types'

export const taskKeys = {
  list: (projectId: string) => ['tasks', projectId] as const,
}

/** No Redux/Zustand: the board IS server state, which is what TanStack Query is for. */
export function useTasks(projectId: string, filters: { search?: string; assignee_id?: string }) {
  return useQuery({
    queryKey: taskKeys.list(projectId),
    queryFn: () => api.tasks(projectId, filters),
    // The stream keeps this fresh; polling would be redundant.
    refetchOnWindowFocus: false,
    staleTime: Infinity,
  })
}

/** Same order as the server's `ORDER BY position, id`. Positions are strings. */
export function tasksInColumn(tasks: Task[], status: TaskStatus): Task[] {
  return tasks
    .filter((t) => t.status === status)
    .sort((a, b) => (a.position < b.position ? -1 : a.position > b.position ? 1 : a.id < b.id ? -1 : 1))
}

interface MoveArgs {
  task: Task
  toStatus: TaskStatus
  beforeId: string | null // land after this task; null = top of column
  afterId: string | null // land before this task; null = bottom
  optimisticPosition: string // where to draw it while the request is in flight
}

export function useMoveTask(projectId: string, onConflict: (message: string) => void) {
  const queryClient = useQueryClient()
  const key = taskKeys.list(projectId)

  return useMutation({
    mutationFn: ({ task, toStatus, beforeId, afterId }: MoveArgs) =>
      api.moveTask(task.id, task.version, toStatus, beforeId, afterId),

    onMutate: async ({ task, toStatus, optimisticPosition }: MoveArgs) => {
      // A refetch already on the wire would land after our optimistic write and stomp
      // it. Not optional.
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
      if (context?.previous) queryClient.setQueryData(key, context.previous)

      if (error instanceof ApiError && error.code === 'version_conflict') {
        // The 409 carries current state, so repair the one card instead of refetching.
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
      // Take the server's position and version. Bumping the version also means the SSE
      // echo of our own change gets dropped by the guard in useProjectStream.
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
    // No optimistic insert. The server assigns the id; faking one buys ~200ms in
    // exchange for a class of reconciliation bugs.
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
