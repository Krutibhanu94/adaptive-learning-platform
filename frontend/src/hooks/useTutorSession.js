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
  // testResult is replaced, not accumulated, on every new Run Test/Submit click -- it
  // reflects only the most recent check, per the test-output panel's "resets on every
  // new click" design. submitResult is set only on a successful submit (final_result +
  // next_problem), separate from testResult since a submit result should persist even
  // after testResult would otherwise be cleared by a subsequent unrelated action.
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState(null)
  const [submitting, setSubmitting] = useState(false)
  const [submitResult, setSubmitResult] = useState(null)

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
      } else if (err.status === 409) {
        // Not fatal, not a connectivity issue -- the engagement gate specifically, so
        // "retrying automatically" would be a misleading message here.
        setError("You need to engage with the tutor before submitting.")
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
    console.log(
      "[code_update] onChange fired -- (re)scheduling debounced send in",
      CODE_DEBOUNCE_MS, "ms. code length:", code.length
    )
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(async () => {
      console.log("[code_update] debounce fired, sending:", code)
      try {
        const data = await sendTurn({ event_type: "code_update", code })
        if (data) {
          // code_changed/stuck_since/struggle_duration_seconds are what the backend
          // actually computed by checking growth/similarity against its own
          // recent_code_snapshots window -- the authoritative answer to "does this
          // register as struggle," not just what the client sent.
          console.log("[code_update] backend response:", {
            code_changed: data.code_changed,
            stuck_since: data.stuck_since,
            struggle_duration_seconds: data.struggle_duration_seconds,
            pending_response_to: data.pending_response_to,
            message: data.message,
          })
          applyResult(data)
        }
      } catch (error) {
        console.error("Error reporting code update:", error)
      }
    }, CODE_DEBOUNCE_MS)
  }, [attemptId, sendTurn, applyResult])

  const runTest = useCallback(async (code) => {
    if (!attemptId) return
    setTesting(true)
    setTestResult(null)
    try {
      const data = await sendTurn({ event_type: "run_test", code })
      if (data) {
        applyResult(data)
        setTestResult(data.run_test_result ?? null)
      }
    } catch (error) {
      console.error("Error running tests:", error)
    } finally {
      setTesting(false)
    }
  }, [attemptId, sendTurn, applyResult])

  const submit = useCallback(async (code) => {
    if (!attemptId) return
    setSubmitting(true)
    try {
      const data = await sendTurn({ event_type: "submit", code })
      if (data) {
        applyResult(data)
        setTestResult(data.run_test_result ?? null)
        setSubmitResult({
          finalResult: data.final_result,
          nextProblem: data.next_problem ?? null,
        })
      }
    } catch (error) {
      // 409 (engagement gate) and any other failure are both already reflected in
      // `error`/`fatal` by sendTurn -- nothing further to do here but avoid an unhandled
      // rejection.
      console.error("Error submitting:", error)
    } finally {
      setSubmitting(false)
    }
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
      // Reset per-attempt error/test state for this fresh attemptId before anything
      // else can set it (e.g. the resume call below, if it 404s immediately).
      setFatal(false)
      setError(null)
      setTestResult(null)
      setSubmitResult(null)
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

  return {
    messages,
    sending,
    gateState,
    error,
    fatal,
    testing,
    testResult,
    submitting,
    submitResult,
    sendMessage,
    reportCodeChange,
    runTest,
    submit,
  }
}

export { useTutorSession }
