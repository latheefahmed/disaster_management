import { useEffect, useRef } from 'react'

type UseLiveAllocationStreamParams = {
  enabled: boolean
  streamUrl: string
  onDelta: () => void
}

export function useLiveAllocationStream({ enabled, streamUrl, onDelta }: UseLiveAllocationStreamParams) {
  const pendingRef = useRef(false)
  const onDeltaRef = useRef(onDelta)

  useEffect(() => {
    onDeltaRef.current = onDelta
  }, [onDelta])

  useEffect(() => {
    if (!enabled || !streamUrl) return

    const source = new EventSource(streamUrl)

    const trigger = () => {
      if (pendingRef.current) return
      pendingRef.current = true
      window.setTimeout(() => {
        pendingRef.current = false
        onDeltaRef.current()
      }, 300)
    }

    source.addEventListener('delta', trigger)
    source.addEventListener('connected', () => undefined)
    source.addEventListener('heartbeat', () => undefined)

    source.onerror = () => undefined

    return () => {
      source.close()
    }
  }, [enabled, streamUrl])
}
