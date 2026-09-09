//this is the chat part of the workspace page.
//lets have a header with the text "AI Tutor" and below it is the scrollable chat area where the user can see the chat history
//  and below that is the input area all the way to the bottom its the static placement where the user can type their message and send it to the AI tutor.
//  The AI tutor will respond with a message and the chat history will be updated accordingly.

import { useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

import "./tutor.css"

function Tutor() {
  const [messages, setMessages] = useState([])
  const [draft, setDraft] = useState("")

  const handleSend = () => {
    const trimmed = draft.trim()
    if (!trimmed) return

    setMessages((prev) => [...prev, { role: "student", text: trimmed }])
    setDraft("")
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
        />
        <Button type="button" className="tutor__send" onClick={handleSend}>
          Send
        </Button>
      </div>
    </div>
  )
}

export default Tutor
