import type { Task } from '../api/types'

interface Props {
  task: Task
  isDragging: boolean
  onDragStart: () => void
  onDragEnd: () => void
  onClick: () => void
}

function initials(name: string): string {
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? '')
    .join('')
}

function dueState(due: string | null): 'overdue' | 'soon' | 'later' | null {
  if (!due) return null
  const days = (new Date(due).getTime() - Date.now()) / 86_400_000
  if (days < 0) return 'overdue'
  if (days < 2) return 'soon'
  return 'later'
}

export function TaskCard({ task, isDragging, onDragStart, onDragEnd, onClick }: Props) {
  const due = dueState(task.due_date)

  return (
    <article
      className={`card ${isDragging ? 'card--dragging' : ''}`}
      draggable
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onClick={onClick}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onClick()
        }
      }}
      tabIndex={0}
      role="button"
      aria-label={`${task.title}. ${task.assignee_name ?? 'Unassigned'}.`}
    >
      <h3 className="card__title">{task.title}</h3>

      {task.description && <p className="card__desc">{task.description}</p>}

      <footer className="card__meta">
        {task.assignee_name ? (
          <span className="avatar" title={task.assignee_name}>
            {initials(task.assignee_name)}
          </span>
        ) : (
          <span className="avatar avatar--empty" title="Unassigned">
            —
          </span>
        )}

        {task.due_date && (
          <time className={`due due--${due}`} dateTime={task.due_date}>
            {new Date(task.due_date).toLocaleDateString(undefined, {
              month: 'short',
              day: 'numeric',
            })}
          </time>
        )}
      </footer>
    </article>
  )
}
