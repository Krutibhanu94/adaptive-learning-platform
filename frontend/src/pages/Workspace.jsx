import { useNavigate } from "react-router-dom"
import { ArrowLeft } from "lucide-react"

import { Button } from "@/components/ui/button"
import CodeEditor from "@/pages/CodeEditor"
import Problem from "@/pages/problem"
import Tutor from "@/pages/tutor"

import "./Workspace.css"

function Workspace() {
  const navigate = useNavigate()

  return (
    <div className="workspace">
      <div className="workspace__main">
        <header className="workspace__header">
          <Button
            type="button"
            aria-label="Back to problems"
            className="workspace__back"
            onClick={() => navigate(-1)}
          >
            <ArrowLeft className="workspace__back-icon" />
          </Button>

          <h1 className="workspace__problem-name">Problem Name</h1>
        </header>

        <div className="workspace__content">
            <div className="workspace__description">
              <Problem
                problemName="Problem Name"
                problemDescription="Problem description placeholder"
              />
            </div>
            <div className="workspace__editor">
              <div className="workspace__code">
                <CodeEditor />
              </div>
              <div className="workspace__testcases">Test cases placeholder</div>
            </div>
        </div>
      </div>

      <div className="workspace__chat">
        <Tutor />
      </div>
    </div>
  )
}

export default Workspace
