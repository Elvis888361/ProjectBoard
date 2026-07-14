import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '../src/api/client'
import { ApiError, type Task } from '../src/api/types'
import { Board } from '../src/components/Board'
import { taskKeys } from '../src/hooks/useTasks'

vi.mock('../src/api/client', () => ({
  api: { moveTask: vi.fn() },
}))

const task = (over: Partial<Task> & { id: string }): Task => ({
  project_id: 'p1',
  title: over.id,
  description: '',
  status: 'todo',
  assignee_id: null,
  assignee_name: null,
  due_date: null,
  position: 'a0',
  version: 1,
  created_at: '2026-07-14T09:00:00Z',
  updated_at: '2026-07-14T09:00:00Z',
  ...over,
})

/**
 * Board takes tasks as a prop, but optimistic updates are written to the query cache --
 * so a static array would never show them. This subscribes to the cache the way
 * BoardPage does, which is what makes the assertions below mean anything.
 */
function BoardHarness({ tasks, onConflict }: { tasks: Task[]; onConflict: () => void }) {
  const { data } = useQuery({
    queryKey: taskKeys.list('p1'),
    queryFn: async () => tasks,
    staleTime: Infinity,
  })
  return (
    <Board projectId="p1" tasks={data ?? []} onOpenTask={vi.fn()} onConflict={onConflict} />
  )
}

function setup(tasks: Task[], onConflict = vi.fn()) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  queryClient.setQueryData(taskKeys.list('p1'), tasks)

  const utils = render(
    <QueryClientProvider client={queryClient}>
      <BoardHarness tasks={tasks} onConflict={onConflict} />
    </QueryClientProvider>,
  )
  return { ...utils, queryClient, onConflict }
}

function dragCardToColumn(title: string, columnName: string) {
  fireEvent.dragStart(screen.getByRole('button', { name: new RegExp(title) }))
  const column = screen.getByRole('region', { name: columnName })
  fireEvent.dragOver(column)
  fireEvent.drop(column)
}

describe('Board', () => {
  beforeEach(() => vi.clearAllMocks())

  it('renders tasks in their status columns, ordered by position', () => {
    setup([
      task({ id: 'second', position: 'a2', status: 'todo' }),
      task({ id: 'first', position: 'a1', status: 'todo' }),
      task({ id: 'shipped', status: 'done' }),
    ])

    const todo = within(screen.getByRole('region', { name: 'Todo' }))
    const cards = todo.getAllByRole('button')

    // By position, not array order. If this regresses, boards silently scramble.
    expect(cards[0]).toHaveTextContent('first')
    expect(cards[1]).toHaveTextContent('second')

    expect(within(screen.getByRole('region', { name: 'Done' })).getByText('shipped')).toBeVisible()
  })

  it('moves the card immediately on drop, before the server responds', async () => {
    // Never settles -- the point is that the UI doesn't wait.
    vi.mocked(api.moveTask).mockReturnValue(new Promise(() => {}))
    setup([task({ id: 'ship-it', status: 'todo', version: 3 })])

    dragCardToColumn('ship-it', 'In Progress')

    await waitFor(() => {
      const inProgress = within(screen.getByRole('region', { name: 'In Progress' }))
      expect(inProgress.getByText('ship-it')).toBeVisible()
    })

    // Empty target column, so no neighbours either side.
    expect(api.moveTask).toHaveBeenCalledWith('ship-it', 3, 'in_progress', null, null)
  })

  it('sends the neighbouring task ids so the server can compute the position', async () => {
    vi.mocked(api.moveTask).mockReturnValue(new Promise(() => {}))
    setup([
      task({ id: 'dragged', status: 'todo', version: 1 }),
      task({ id: 'top', status: 'done', position: 'a1' }),
      task({ id: 'bottom', status: 'done', position: 'a2' }),
    ])

    dragCardToColumn('dragged', 'Done')

    // Dropping on the column, not a card, appends.
    await waitFor(() =>
      expect(api.moveTask).toHaveBeenCalledWith('dragged', 1, 'done', 'bottom', null),
    )
  })

  it('rolls the card back and reports the conflict when the server rejects the move', async () => {
    // Held open so the optimistic state is observable. An immediately-rejecting mock
    // would roll back in the same tick, and this test would pass even with the
    // optimistic update removed entirely.
    let reject!: (error: unknown) => void
    vi.mocked(api.moveTask).mockReturnValue(
      new Promise((_resolve, rej) => {
        reject = rej
      }),
    )

    const { onConflict } = setup([task({ id: 'contested', status: 'todo', version: 1 })])

    dragCardToColumn('contested', 'In Progress')

    // Optimistically lands in In Progress...
    await waitFor(() =>
      expect(
        within(screen.getByRole('region', { name: 'In Progress' })).getByText('contested'),
      ).toBeVisible(),
    )

    // Someone else got there first.
    reject(
      new ApiError(409, 'version_conflict', 'This task was moved by someone else.', {
        current: task({ id: 'contested', status: 'done', version: 9 }),
      }),
    )

    // ...then rolls back, and the user is told why. Reverting silently would be worse
    // than not moving at all.
    await waitFor(() =>
      expect(
        within(screen.getByRole('region', { name: 'In Progress' })).queryByText('contested'),
      ).not.toBeInTheDocument(),
    )
    expect(onConflict).toHaveBeenCalledWith('This task was moved by someone else.')
  })

  it('does not send a request when a card is dropped back where it started', () => {
    setup([task({ id: 'unmoved', status: 'todo' })])

    dragCardToColumn('unmoved', 'Todo')

    expect(api.moveTask).not.toHaveBeenCalled()
  })
})
