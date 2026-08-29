import { User } from "lucide-react"

import "./appBar.css"

function AppBar({ userName }) {
  return (
    <header className="app-bar">
      <span aria-label="Adaptive Tutor logo" className="app-bar__logo">
        A
      </span>

      <div className="app-bar__profile">
        {userName && <span className="app-bar__profile-name">{userName}</span>}

        <button type="button" aria-label="User profile" className="app-bar__profile-btn">
          <User className="app-bar__profile-icon" strokeWidth={2.5} />
        </button>
      </div>
    </header>
  )
}

export { AppBar }
