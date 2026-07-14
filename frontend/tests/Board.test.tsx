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

    expect(cards[0]).toHaveTextContent('first')
    expect(cards[1]).toHaveTextContent('second')

    expect(within(screen.getByRole('region', { name: 'Done' })).getByText('shipped')).toBeVisible()
  })

  it('moves the card immediately on drop, before the server responds', async () => {
    vi.mocked(api.moveTask).mockReturnValue(new Promise(() => {}))
    setup([task({ id: 'ship-it', status: 'todo', version: 3 })])

    dragCardToColumn('ship-it', 'In Progress')

    await waitFor(() => {
      const inProgress = within(screen.getByRole('region', { name: 'In Progress' }))
      expect(inProgress.getByText('ship-it')).toBeVisible()
    })

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

    await waitFor(() =>
      expect(api.moveTask).toHaveBeenCalledWith('dragged', 1, 'done', 'bottom', null),
    )
  })

  it('rolls the card back and reports the conflict when the server rejects the move', async () => {
    let reject!: (error: unknown) => void
    vi.mocked(api.moveTask).mockReturnValue(
      new Promise((_resolve, rej) => {
        reject = rej
      }),
    )

    const { onConflict } = setup([task({ id: 'contested', status: 'todo', version: 1 })])

    dragCardToColumn('contested', 'In Progress')

    await waitFor(() =>
      expect(
        within(screen.getByRole('region', { name: 'In Progress' })).getByText('contested'),
      ).toBeVisible(),
    )

    reject(
      new ApiError(409, 'version_conflict', 'This task was moved by someone else.', {
        current: task({ id: 'contested', status: 'done', version: 9 }),
      }),
    )

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
