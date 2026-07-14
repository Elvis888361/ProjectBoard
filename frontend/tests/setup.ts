import '@testing-library/jest-dom/vitest'

class EventSourceStub {
  static readonly CLOSED = 2
  readyState = 0
  withCredentials = false
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
  addEventListener() {}
  removeEventListener() {}
  close() {}
}

vi.stubGlobal('EventSource', EventSourceStub)
