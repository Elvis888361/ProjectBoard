import '@testing-library/jest-dom/vitest'

// jsdom has no EventSource. The live stream is covered by the backend tests, which
// drive a real one, so a stub is enough to let components mount.
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
