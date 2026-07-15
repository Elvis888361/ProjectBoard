import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../api/client'
import { ApiError } from '../api/types'

export function LoginPage() {
  const queryClient = useQueryClient()
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [displayName, setDisplayName] = useState('')
  const [error, setError] = useState<string | null>(null)

  const passwordLongEnough = password.length >= 8

  const submit = useMutation({
    mutationFn: () =>
      mode === 'login'
        ? api.login(email, password)
        : api.register(email, password, displayName),
    onSuccess: (user) => {
      setError(null)
      queryClient.setQueryData(['me'], user)
    },
    onError: (e) => {
      setError(e instanceof ApiError ? e.message : 'Something went wrong. Try again.')
    },
  })

  return (
    <div className="auth">
      <form
        className="auth__card"
        onSubmit={(e) => {
          e.preventDefault()
          submit.mutate()
        }}
      >
        <h1>ProjectBoard</h1>
        <p className="auth__sub">
          {mode === 'login' ? 'Sign in to your boards.' : 'Create an account.'}
        </p>

        {mode === 'register' && (
          <label>
            Name
            <input
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              required
              maxLength={80}
              autoComplete="name"
            />
          </label>
        )}

        <label>
          Email
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoComplete="email"
          />
        </label>

        <label>
          Password
          <div className="password-field">
            <input
              type={showPassword ? 'text' : 'password'}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              minLength={8}
              autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
            />
            <button
              type="button"
              className="password-toggle"
              onClick={() => setShowPassword((s) => !s)}
              aria-label={showPassword ? 'Hide password' : 'Show password'}
              title={showPassword ? 'Hide password' : 'Show password'}
            >
              {showPassword ? <EyeOffIcon /> : <EyeIcon />}
            </button>
          </div>
          {mode === 'register' && (
            <small className={passwordLongEnough ? 'auth__hint auth__hint--ok' : 'auth__hint'}>
              {passwordLongEnough ? '✓ Looks good' : 'At least 8 characters.'}
            </small>
          )}
        </label>

        {error && (
          <p className="auth__error" role="alert">
            {error}
          </p>
        )}

        <button className="btn btn--primary btn--block" disabled={submit.isPending}>
          {submit.isPending ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}
        </button>

        <button
          type="button"
          className="auth__toggle"
          onClick={() => {
            setMode(mode === 'login' ? 'register' : 'login')
            setError(null)
          }}
        >
          {mode === 'login' ? 'Need an account? Sign up' : 'Already have an account? Sign in'}
        </button>
      </form>
    </div>
  )
}

const iconProps = {
  width: 18,
  height: 18,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.7,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
}

function EyeIcon() {
  return (
    <svg {...iconProps} aria-hidden>
      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  )
}

function EyeOffIcon() {
  return (
    <svg {...iconProps} aria-hidden>
      <path d="M9.9 4.24A9.1 9.1 0 0 1 12 4c6.5 0 10 7 10 7a13.2 13.2 0 0 1-1.67 2.44" />
      <path d="M6.1 6.1A13.3 13.3 0 0 0 2 11s3.5 7 10 7a9 9 0 0 0 5-1.4" />
      <path d="M9.9 9.9a3 3 0 0 0 4.2 4.2" />
      <path d="m2 2 20 20" />
    </svg>
  )
}
