import '@testing-library/jest-dom/vitest'

// jsdom has no EventSource. The board test doesn't exercise the live stream (that's
// covered by the backend integration test, which drives a real one), so a stub is
// enough to let the component mount without blowing up.
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
