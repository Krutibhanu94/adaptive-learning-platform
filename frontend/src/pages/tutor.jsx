import { useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

import "./tutor.css"

function Tutor({ messages, sending, error, fatal, onSendMessage }) {
  const [draft, setDraft] = useState("")

  const handleSend = () => {
    const trimmed = draft.trim()
    if (!trimmed || sending || fatal) return

    setDraft("")
    onSendMessage(trimmed)
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

      {error && <div className="tutor__error">{error}</div>}

      <div className="tutor__input-row">
        <Input
          type="text"
          placeholder="Ask the tutor..."
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={handleKeyDown}
          disabled={sending || fatal}
        />
        <Button type="button" className="tutor__send" onClick={handleSend} disabled={sending || fatal}>
          Send
        </Button>
      </div>
    </div>
  )
}

export default Tutor
