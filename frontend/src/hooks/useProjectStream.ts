import { useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'

import type { Task } from '../api/types'
import { taskKeys } from './useTasks'

export type StreamStatus = 'connecting' | 'live' | 'reconnecting'

interface BoardEvent {
  id: number
  type: 'task.created' | 'task.updated' | 'task.moved' | 'task.deleted'
  payload: { task?: Task; task_id?: string }
}

export function useProjectStream(projectId: string | undefined): StreamStatus {
  const queryClient = useQueryClient()
  const [status, setStatus] = useState<StreamStatus>('connecting')

  useEffect(() => {
    if (!projectId) return

    const source = new EventSource(`/api/v1/projects/${projectId}/events`, {
      withCredentials: true,
    })
    const key = taskKeys.list(projectId)

    const apply = (event: MessageEvent) => {
      setStatus('live')
      const board = JSON.parse(event.data) as BoardEvent

      queryClient.setQueryData<Task[]>(key, (tasks) => {
        if (!tasks) return tasks

        if (board.type === 'task.deleted') {
          return tasks.filter((t) => t.id !== board.payload.task_id)
        }

        const incoming = board.payload.task
        if (!incoming) return tasks

        const existing = tasks.find((t) => t.id === incoming.id)
        if (!existing) return [...tasks, incoming]

        if (incoming.version <= existing.version) return tasks

        return tasks.map((t) => (t.id === incoming.id ? incoming : t))
      })
    }

    for (const type of ['task.created', 'task.updated', 'task.moved', 'task.deleted']) {
      source.addEventListener(type, apply)
    }
    source.addEventListener('synced', () => setStatus('live'))

    source.onopen = () => setStatus('live')
    source.onerror = () => setStatus('reconnecting')

    return () => source.close()
  }, [projectId, queryClient])

  return status
}
