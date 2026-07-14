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

  // Native HTML5 DnD, no library. Not keyboard accessible -- the dialog's status select
  // is the keyboard path. A production board would use dnd-kit.
  const drop = (status: TaskStatus, beforeIndex: number) => {
    setTarget(null)
    const task = dragging
    setDragging(null)
    if (!task) return

    const column = tasksInColumn(tasks, status).filter((t) => t.id !== task.id)

    // Dragging a card two pixels shouldn't burn a round trip, bump a version, and fire
    // an event at everyone else on the board.
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
      // Only for the ~50ms the request is in flight; onSuccess takes the server's.
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
                    // Above or below, depending on which half the cursor is in.
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
