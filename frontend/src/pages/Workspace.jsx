import { useNavigate, useLocation, useParams } from "react-router-dom"
import { ArrowLeft } from "lucide-react"

import { Button } from "@/components/ui/button"
import CodeEditor from "@/pages/CodeEditor"
import Problem from "@/pages/problem"
import Tutor from "@/pages/tutor"

import "./Workspace.css"

function Workspace() {
  const navigate = useNavigate()
  const location = useLocation()
  const { attemptId } = useParams()

  // Only populated when navigated here from TopicProblems' Start Problem button --
  // there's no GET /attempts/{attempt_id} rehydration endpoint yet, so a direct visit
  // or a page refresh currently has no way to recover the problem data. Known gap.
  const problem = location.state?.problem

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
                <CodeEditor />
              </div>
              <div className="workspace__testcases">Test cases placeholder</div>
            </div>
        </div>
      </div>

      <div className="workspace__chat">
        <Tutor attemptId={attemptId} />
      </div>
    </div>
  )
}

export default Workspace
