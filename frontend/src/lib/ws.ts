import { useSyncExternalStore } from "react"

// Genau EINE WebSocket-Verbindung -- zum Backend, nie zur Bruecke. Der Kanal
// ist server->client; geschrieben wird ausschliesslich ueber HTTP.
//
// Verpasste Ereignisse werden nicht nachgeholt: bei jedem (Wieder-)Verbinden
// schickt das Backend "hello", und der Empfaenger laedt dann neu.

export type SocketState = "connecting" | "open" | "closed"
export type Frame = { type: string; [key: string]: unknown }
type FrameListener = (frame: Frame) => void

const MIN_DELAY_MS = 500
const MAX_DELAY_MS = 5_000

class EventSocket {
  private socket: WebSocket | null = null
  private delay = MIN_DELAY_MS
  private timer: ReturnType<typeof setTimeout> | null = null
  private frameListeners = new Set<FrameListener>()
  private stateListeners = new Set<() => void>()
  state: SocketState = "closed"

  start() {
    if (this.socket || this.timer) return
    this.connect()
  }

  onFrame(listener: FrameListener) {
    this.frameListeners.add(listener)
    return () => {
      this.frameListeners.delete(listener)
    }
  }

  subscribe = (listener: () => void) => {
    this.stateListeners.add(listener)
    return () => {
      this.stateListeners.delete(listener)
    }
  }

  private setState(state: SocketState) {
    this.state = state
    this.stateListeners.forEach((listener) => listener())
  }

  private connect() {
    this.timer = null
    this.setState("connecting")
    const protocol = location.protocol === "https:" ? "wss:" : "ws:"
    const socket = new WebSocket(protocol + "//" + location.host + "/ws")
    this.socket = socket

    socket.onopen = () => {
      this.delay = MIN_DELAY_MS
      this.setState("open")
    }
    socket.onmessage = (message) => {
      let frame: Frame
      try {
        frame = JSON.parse(message.data as string) as Frame
      } catch {
        return
      }
      this.frameListeners.forEach((listener) => listener(frame))
    }
    socket.onclose = () => {
      this.socket = null
      this.setState("closed")
      this.timer = setTimeout(() => this.connect(), this.delay)
      this.delay = Math.min(this.delay * 2, MAX_DELAY_MS)
    }
  }
}

export const eventSocket = new EventSocket()

export function useSocketState(): SocketState {
  return useSyncExternalStore(eventSocket.subscribe, () => eventSocket.state)
}
