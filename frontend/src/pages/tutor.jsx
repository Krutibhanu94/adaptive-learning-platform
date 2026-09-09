import { useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

import "./tutor.css"

function Tutor({ attemptId }) {
  const [messages, setMessages] = useState([])
  const [draft, setDraft] = useState("")
  const [sending, setSending] = useState(false)

  const handleSend = async () => {
    const trimmed = draft.trim()
    if (!trimmed || !attemptId || sending) return

    setMessages((prev) => [...prev, { role: "student", text: trimmed }])
    setDraft("")
    setSending(true)

    try {
      const response = await fetch(`http://localhost:8000/attempts/${attemptId}/turn`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ event_type: "message", message: trimmed }),
      })

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }

      const data = await response.json()

      if (data.message) {
        setMessages((prev) => [...prev, { role: "tutor", text: data.message }])
      }
    } catch (error) {
      console.error("Error sending message to tutor:", error)
    } finally {
      setSending(false)
    }
  }

  const handleKeyDown = (event) => {
    if (event.key === "Enter") {
      handleSend()
    }
  }

  return (
    <div className="tutor">
      <header className="tutor__bar">
        <h2 className="tutor__header">AI Tutor</h2>
      </header>

      <div className="tutor__messages">
        {messages.map((message, index) => (
          <div key={index} className={`tutor__message tutor__message--${message.role}`}>
            {message.text}
          </div>
        ))}
      </div>

      <div className="tutor__input-row">
        <Input
          type="text"
          placeholder="Ask the tutor..."
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={handleKeyDown}
          disabled={sending}
        />
        <Button type="button" className="tutor__send" onClick={handleSend} disabled={sending}>
          Send
        </Button>
      </div>
    </div>
  )
}

export default Tutor
