import { useCallback, useEffect, useRef, useState } from "react"

const HEARTBEAT_INTERVAL_MS = 20000
const CODE_DEBOUNCE_MS = 2000

function storageKey(attemptId) {
  return `tutor-messages-${attemptId}`
}

function loadCachedMessages(attemptId) {
  try {
    const raw = localStorage.getItem(storageKey(attemptId))
    return raw ? JSON.parse(raw) : null
  } catch (error) {
    console.error("Error reading cached chat history:", error)
    return null
  }
}

function useTutorSession(attemptId) {
  const [messages, setMessages] = useState([])
  const [sending, setSending] = useState(false)
  const [gateState, setGateState] = useState({
    engagementOccurred: false,
    tier: null,
    hintCap: null,
    hintsUsed: 0,
    escalated: false,
    escalationReason: null,
  })
  // error is a user-facing message, or null when there's nothing wrong. fatal marks a
  // 404 specifically (the attempt genuinely doesn't exist) -- unlike a transient network
  // blip, retrying can't fix that, so further requests for this attemptId are skipped
  // outright rather than silently failing over and over.
  const [error, setError] = useState(null)
  const [fatal, setFatal] = useState(false)

  const debounceRef = useRef(null)
  const busyRef = useRef(false)
  const hydratedRef = useRef(false)
  const fatalRef = useRef(false)

  const applyResult = useCallback((data) => {
    setGateState({
      engagementOccurred: data.engagement_occurred,
      tier: data.tier,
      hintCap: data.hint_cap,
      hintsUsed: data.hints_used,
      escalated: data.escalated,
      escalationReason: data.escalation_reason,
    })
    if (data.message) {
      setMessages((prev) => [...prev, { role: "tutor", text: data.message }])
    }
  }, [])

  const sendTurn = useCallback(async (body) => {
    if (!attemptId || fatalRef.current) return null
    busyRef.current = true
    try {
      const response = await fetch(`http://localhost:8000/attempts/${attemptId}/turn`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
      if (!response.ok) {
        const err = new Error(`HTTP error! status: ${response.status}`)
        err.status = response.status
        throw err
      }
      setError(null)
      return await response.json()
    } catch (err) {
      // A silent console.error here is indistinguishable from the tutor just not
      // having anything to say -- surface it visibly instead.
      if (err.status === 404) {
        fatalRef.current = true
        setFatal(true)
        setError("This problem session is no longer available. Go back and start a new attempt.")
      } else {
        setError("Having trouble reaching the tutor -- retrying automatically.")
      }
      throw err
    } finally {
      busyRef.current = false
    }
  }, [attemptId])

  const sendMessage = useCallback(async (text) => {
    const trimmed = text.trim()
    if (!trimmed || !attemptId) return

    setMessages((prev) => [...prev, { role: "student", text: trimmed }])
    setSending(true)
    try {
      const data = await sendTurn({ event_type: "message", message: trimmed })
      if (data) applyResult(data)
    } catch (error) {
      console.error("Error sending message to tutor:", error)
    } finally {
      setSending(false)
    }
  }, [attemptId, sendTurn, applyResult])

  const reportCodeChange = useCallback((code) => {
    if (!attemptId) return
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(async () => {
      try {
        const data = await sendTurn({ event_type: "code_update", code })
        if (data) applyResult(data)
      } catch (error) {
        console.error("Error reporting code update:", error)
      }
    }, CODE_DEBOUNCE_MS)
  }, [attemptId, sendTurn, applyResult])

  // Rehydrate on load. The full transcript, if this browser has one cached from an
  // earlier visit to this attempt, wins -- the backend only ever has the single
  // currently-outstanding question (interaction_log stores turn summaries, not verbatim
  // text), so it's strictly worse than a cached transcript and only used as a fallback
  // for a fresh browser/device that's never seen this attempt before.
  useEffect(() => {
    hydratedRef.current = false
    fatalRef.current = false
    if (!attemptId) return undefined
    let cancelled = false

    const cachedMessages = loadCachedMessages(attemptId)

    const rehydrate = async () => {
      // Reset per-attempt error state for this fresh attemptId before anything else
      // can set it (e.g. the resume call below, if it 404s immediately).
      setFatal(false)
      setError(null)
      try {
        // Mark this as real activity first, before anything else reads state -- this is
        // the reopen-triggers-escalation fix for the paths that skip /start's own resume
        // branch (a browser back/forward or refresh straight into an existing Workspace).
        // A stale last_activity_at from before a closed tab/navigated-away gap would
        // otherwise get misread as idle struggle by the next heartbeat.
        const resumeData = await sendTurn({ event_type: "resume" })

        const response = await fetch(`http://localhost:8000/attempts/${attemptId}`)
        const data = response.ok ? await response.json() : null
        if (cancelled) return

        const gate = resumeData ?? data
        if (gate) {
          setGateState({
            engagementOccurred: gate.engagement_occurred,
            tier: gate.tier,
            hintCap: gate.hint_cap,
            hintsUsed: gate.hints_used,
            escalated: gate.escalated,
            escalationReason: gate.escalation_reason,
          })
        }

        if (cachedMessages && cachedMessages.length > 0) {
          setMessages(cachedMessages)
        } else if (data?.current_message) {
          setMessages([{ role: "tutor", text: data.current_message }])
        } else {
          setMessages([])
        }
      } catch (error) {
        console.error("Error rehydrating attempt state:", error)
      } finally {
        if (!cancelled) hydratedRef.current = true
      }
    }

    rehydrate()
    return () => {
      cancelled = true
    }
  }, [attemptId, sendTurn])

  // Cache the transcript for this attempt so a refresh in the same browser recovers it.
  // Gated on hydratedRef so the initial empty [] (before rehydrate resolves) doesn't
  // stomp an already-cached transcript.
  useEffect(() => {
    if (!attemptId || !hydratedRef.current) return
    try {
      localStorage.setItem(storageKey(attemptId), JSON.stringify(messages))
    } catch (error) {
      console.error("Error caching chat history:", error)
    }
  }, [attemptId, messages])

  // Heartbeat: a periodic idle-time check, skipped if something else is already
  // mid-flight so it doesn't race a message send or code-update report.
  useEffect(() => {
    if (!attemptId) return undefined

    const interval = setInterval(async () => {
      if (busyRef.current) return
      try {
        const data = await sendTurn({ event_type: "heartbeat" })
        if (data) applyResult(data)
      } catch (error) {
        console.error("Error sending heartbeat:", error)
      }
    }, HEARTBEAT_INTERVAL_MS)

    return () => clearInterval(interval)
  }, [attemptId, sendTurn, applyResult])

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [])

  return { messages, sending, gateState, error, fatal, sendMessage, reportCodeChange }
}

export { useTutorSession }
