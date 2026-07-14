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

/**
 * Consumes the project's SSE stream and patches the query cache in place.
 *
 * We patch rather than refetch -- the event carries the whole task, and refetching on
 * every event would turn one person's drag into an HTTP request from every connected
 * client.
 *
 * Reconnection is the browser's job. EventSource retries and replays Last-Event-ID, and
 * the server streams the gap. That's why this file is short.
 */
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

        // The version guard. Without it, an event generated before your optimistic move
        // lands after it and the card snaps back. Server versions are monotonic, so
        // out-of-order delivery is harmless by construction rather than by luck.
        if (incoming.version <= existing.version) return tasks

        return tasks.map((t) => (t.id === incoming.id ? incoming : t))
      })
    }

    for (const type of ['task.created', 'task.updated', 'task.moved', 'task.deleted']) {
      source.addEventListener(type, apply)
    }
    source.addEventListener('synced', () => setStatus('live'))

    source.onopen = () => setStatus('live')
    // Don't reconnect by hand here -- it just fights the browser's own backoff.
    source.onerror = () => setStatus('reconnecting')

    return () => source.close()
  }, [projectId, queryClient])

  return status
}
