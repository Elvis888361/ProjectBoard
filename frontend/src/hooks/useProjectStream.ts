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
 * Consumes the project's SSE stream and patches the TanStack Query cache in place.
 *
 * Two things here are the difference between "realtime works" and "realtime works
 * until two people touch the same card":
 *
 * 1. THE VERSION GUARD. An event that arrives describing version 4 of a task, when the
 *    cache already holds version 5, is stale and must be dropped. Without this, the
 *    classic race bites: you optimistically move a card, an event generated *before*
 *    your write lands, and the card snaps back to where it was. Server versions are
 *    monotonic, so comparing them makes out-of-order delivery harmless by construction
 *    rather than by timing luck.
 *
 * 2. WE PATCH, WE DON'T REFETCH. The event carries the whole task, so applying it is a
 *    local cache write with no network round trip. Refetching the board on every event
 *    would work, but it turns one person dragging a card into N HTTP requests across
 *    every connected client -- a self-inflicted thundering herd.
 *
 * Reconnection is the browser's job, not ours. EventSource retries automatically and
 * replays `Last-Event-ID` back to the server, which streams the gap out of the events
 * table. That is the entire reconnect story, and it's why this file is short.
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

        // (1) The version guard. Older-or-equal means we already have this, or we have
        // something newer -- either way, applying it would move the board backwards.
        if (incoming.version <= existing.version) return tasks

        return tasks.map((t) => (t.id === incoming.id ? incoming : t))
      })
    }

    for (const type of ['task.created', 'task.updated', 'task.moved', 'task.deleted']) {
      source.addEventListener(type, apply)
    }
    source.addEventListener('synced', () => setStatus('live'))

    source.onopen = () => setStatus('live')
    source.onerror = () => {
      // EventSource retries on its own, using the `retry:` interval the server sent,
      // and replays Last-Event-ID when it gets back. There is nothing to do here but
      // tell the user -- a manual reconnect would just fight the browser's backoff.
      setStatus('reconnecting')
    }

    return () => source.close()
  }, [projectId, queryClient])

  return status
}
