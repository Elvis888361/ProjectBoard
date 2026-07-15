import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { api } from '../api/client'
import { ApiError } from '../api/types'

export function LoginPage() {
  const queryClient = useQueryClient()
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [error, setError] = useState<string | null>(null)

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
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={8}
            autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
          />
          {mode === 'register' && <small>At least 8 characters.</small>}
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
