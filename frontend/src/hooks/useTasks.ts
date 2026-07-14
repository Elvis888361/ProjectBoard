import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from '../api/client'
import { ApiError, type Task, type TaskStatus } from '../api/types'

export const taskKeys = {
  list: (projectId: string) => ['tasks', projectId] as const,
}

export function useTasks(projectId: string, filters: { search?: string; assignee_id?: string }) {
  return useQuery({
    queryKey: taskKeys.list(projectId),
    queryFn: () => api.tasks(projectId, filters),
    refetchOnWindowFocus: false,
    staleTime: Infinity,
  })
}

export function tasksInColumn(tasks: Task[], status: TaskStatus): Task[] {
  return tasks
    .filter((t) => t.status === status)
    .sort((a, b) => (a.position < b.position ? -1 : a.position > b.position ? 1 : a.id < b.id ? -1 : 1))
}

interface MoveArgs {
  task: Task
  toStatus: TaskStatus
  beforeId: string | null
  afterId: string | null
  optimisticPosition: string
}

export function useMoveTask(projectId: string, onConflict: (message: string) => void) {
  const queryClient = useQueryClient()
  const key = taskKeys.list(projectId)

  return useMutation({
    mutationFn: ({ task, toStatus, beforeId, afterId }: MoveArgs) =>
      api.moveTask(task.id, task.version, toStatus, beforeId, afterId),

    onMutate: async ({ task, toStatus, optimisticPosition }: MoveArgs) => {

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
