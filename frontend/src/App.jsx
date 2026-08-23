import { useState } from 'react'
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"
import './App.css'

function App() {
  const [inputValue, setInputValue] = useState('');
  const [message, setMessage] = useState(null);

  const handleSend = async () => {
      try {
        const response = await fetch('http://localhost:8000/ping', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ message: inputValue }),
        })

        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`)
        }

        const data = await response.json()
        console.log("Response data:", data)
        setMessage(data)
      } catch (error) {
        console.error('Error fetching data:', error)
      }
  }

  return (
    <>
<section id="center">
  <div>
    <h1>Adaptive Tutor — Test</h1>
    <p>Type a message and send it to the agent.</p>
  </div>

  <div style={{ display: "flex", gap: "8px", marginTop: "16px" }}>
    <Input
      type="text"
      placeholder="Type your message..."
      value={inputValue}
      onChange={(e) => setInputValue(e.target.value)}
    />
    <Button onClick={handleSend}>Send</Button>
  </div>

  {message && (
    <div style={{ marginTop: "16px", textAlign: "left" }}>
      <p><strong>Reply:</strong> {message.reply}</p>
      <p><strong>DB check:</strong> {message.db_check}</p>
    </div>
  )}
</section>
    </>
  )
}

export default App
