import { useState } from 'react'

import { keyBetween } from '../lib/ranking'
import { STATUSES, type Task, type TaskStatus } from '../api/types'
import { tasksInColumn, useMoveTask } from '../hooks/useTasks'
import { TaskCard } from './TaskCard'

interface Props {
  projectId: string
  tasks: Task[]
  onOpenTask: (task: Task) => void
  onConflict: (message: string) => void
}

/** Where the drop would land: above a specific card, or at the end of a column. */
interface DropTarget {
  status: TaskStatus
  beforeIndex: number
}

export function Board({ projectId, tasks, onOpenTask, onConflict }: Props) {
  const move = useMoveTask(projectId, onConflict)
  const [dragging, setDragging] = useState<Task | null>(null)
  const [target, setTarget] = useState<DropTarget | null>(null)

  // Native HTML5 drag-and-drop, not @dnd-kit or react-beautiful-dnd. It's zero
  // dependencies and about forty lines. The honest cost is that it is not keyboard
  // accessible -- so the task dialog also has a plain status <select>, which means
  // every drag is achievable without a mouse even though the drag itself isn't.
  // A production board would use dnd-kit for the accessible sensors.
  const drop = (status: TaskStatus, beforeIndex: number) => {
    setTarget(null)
    const task = dragging
    setDragging(null)
    if (!task) return

    const column = tasksInColumn(tasks, status).filter((t) => t.id !== task.id)

    // Skip the write entirely if the card is already where it's being dropped. Dragging
    // a card two pixels shouldn't burn a round trip, bump a version, and fire an event
    // at everyone else on the board.
    const currentIndex = tasksInColumn(tasks, status).findIndex((t) => t.id === task.id)
    if (task.status === status && (currentIndex === beforeIndex || currentIndex === beforeIndex - 1)) {
      return
    }

    const before = column[beforeIndex - 1] ?? null
    const after = column[beforeIndex] ?? null

    move.mutate({
      task,
      toStatus: status,
      beforeId: before?.id ?? null,
      afterId: after?.id ?? null,
      // The server recomputes this authoritatively; we generate the same key locally
      // just so the card renders in the right slot during the ~50ms the request is in
      // flight. The two agree because it's the same algorithm -- and if they ever
      // didn't, onSuccess overwrites ours with the server's.
      optimisticPosition: keyBetween(before?.position ?? null, after?.position ?? null),
    })
  }

  return (
    <div className="board">
      {STATUSES.map(({ id, label }) => {
        const column = tasksInColumn(tasks, id)
        const isTargetColumn = target?.status === id

        return (
          <section
            key={id}
            className={`column ${dragging ? 'column--dropzone' : ''}`}
            aria-label={label}
            onDragOver={(e) => {
              e.preventDefault()
              if (!isTargetColumn) setTarget({ status: id, beforeIndex: column.length })
            }}
            onDrop={(e) => {
              e.preventDefault()
              drop(id, target?.status === id ? target.beforeIndex : column.length)
            }}
          >
            <header className="column__header">
              <h2>{label}</h2>
              <span className="column__count">{column.length}</span>
            </header>

            <div className="column__body">
              {column.map((task, index) => (
                <div
                  key={task.id}
                  onDragOver={(e) => {
                    e.preventDefault()
                    e.stopPropagation()
                    // Above or below this card, depending on which half the cursor is in.
                    const box = e.currentTarget.getBoundingClientRect()
                    const above = e.clientY < box.top + box.height / 2
                    setTarget({ status: id, beforeIndex: above ? index : index + 1 })
                  }}
                >
                  {isTargetColumn && target.beforeIndex === index && <div className="drop-line" />}
                  <TaskCard
                    task={task}
                    isDragging={dragging?.id === task.id}
                    onDragStart={() => setDragging(task)}
                    onDragEnd={() => {
                      setDragging(null)
                      setTarget(null)
                    }}
                    onClick={() => onOpenTask(task)}
                  />
                </div>
              ))}

              {isTargetColumn && target.beforeIndex >= column.length && <div className="drop-line" />}

              {column.length === 0 && !dragging && (
                <p className="column__empty">
                  {id === 'todo' ? 'No tasks yet. Add one above.' : 'Drag a task here.'}
                </p>
              )}
            </div>
          </section>
        )
      })}
    </div>
  )
}
