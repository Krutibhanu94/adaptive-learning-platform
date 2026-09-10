import { useEffect, useState } from "react"
import { useNavigate, useLocation, useParams } from "react-router-dom"
import { ArrowLeft } from "lucide-react"

import { Button } from "@/components/ui/button"
import CodeEditor from "@/pages/CodeEditor"
import Problem from "@/pages/problem"
import Tutor from "@/pages/tutor"
import { useTutorSession } from "@/hooks/useTutorSession"

import "./Workspace.css"

function Workspace() {
  const navigate = useNavigate()
  const location = useLocation()
  const { attemptId } = useParams()

  // Populated directly when navigated here from TopicProblems' Start Problem button;
  // falls back to GET /attempts/{attempt_id} below for a direct visit or page refresh.
  const [problem, setProblem] = useState(location.state?.problem ?? null)
  const { messages, sending, error, fatal, reportCodeChange, sendMessage } = useTutorSession(attemptId)

  useEffect(() => {
    if (problem || !attemptId) return
    let cancelled = false

    fetch(`http://localhost:8000/attempts/${attemptId}`)
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        if (cancelled || !data?.problem_name) return
        setProblem({
          problem_id: data.problem_id,
          problem_name: data.problem_name,
          problem_description: data.problem_description,
        })
      })
      .catch((error) => console.error("Error loading problem:", error))

    return () => {
      cancelled = true
    }
  }, [attemptId, problem])

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

          <h1 className="workspace__problem-name">
            {problem?.problem_name ?? "Problem not loaded"}
          </h1>
        </header>

        <div className="workspace__content">
            <div className="workspace__description">
              <Problem
                problemName={problem?.problem_name}
                problemDescription={
                  problem?.problem_description ??
                  "Open this workspace via Start Problem on the topic's problem list."
                }
              />
            </div>
            <div className="workspace__editor">
              <div className="workspace__code">
                <CodeEditor onChange={reportCodeChange} />
              </div>
              <div className="workspace__testcases">Test cases placeholder</div>
            </div>
        </div>
      </div>

      <div className="workspace__chat">
        <Tutor
          messages={messages}
          sending={sending}
          error={error}
          fatal={fatal}
          onSendMessage={sendMessage}
        />
      </div>
    </div>
  )
}

export default Workspace
