import { useEffect, useRef, useState } from "react"
import { useNavigate, useLocation, useParams } from "react-router-dom"
import { ArrowLeft } from "lucide-react"

import { Button } from "@/components/ui/button"
import CodeEditor from "@/pages/CodeEditor"
import Problem from "@/pages/problem"
import TestOutput from "@/pages/TestOutput"
import Tutor from "@/pages/tutor"
import { useTutorSession } from "@/hooks/useTutorSession"
import { useStudent } from "@/context/useStudent"

import "./Workspace.css"

function Workspace() {
  const navigate = useNavigate()
  const location = useLocation()
  const { topicId, attemptId } = useParams()
  const student = useStudent()
  const codeEditorRef = useRef(null)

  // Populated directly when navigated here from TopicProblems' Start Problem button (or
  // this page's own Next Problem button); falls back to GET /attempts/{attempt_id}
  // below for a direct visit, a refresh, or anything else that skips router state.
  const [problem, setProblem] = useState(location.state?.problem ?? null)

  // location.state doesn't change on its own when attemptId changes (Workspace stays
  // mounted for a Next Problem navigation, same route pattern) -- without resetting,
  // `problem` would keep showing the previous attempt's data. Adjusting state during
  // render (React's own recommended pattern for "reset when a param changes") rather
  // than in an effect, to avoid an extra render pass.
  const [renderedAttemptId, setRenderedAttemptId] = useState(attemptId)
  if (attemptId !== renderedAttemptId) {
    setRenderedAttemptId(attemptId)
    setProblem(location.state?.problem ?? null)
  }

  const {
    messages,
    sending,
    error,
    fatal,
    testing,
    testResult,
    submitting,
    submitResult,
    gateState,
    reportCodeChange,
    sendMessage,
    runTest,
    submit,
  } = useTutorSession(attemptId)

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
          test_cases: data.test_cases,
          starter_code: data.starter_code,
        })
      })
      .catch((error) => console.error("Error loading problem:", error))

    return () => {
      cancelled = true
    }
  }, [attemptId, problem])

  const handleRunTest = () => {
    if (testing || submitting || fatal || submitResult) return
    runTest(codeEditorRef.current?.getValue() ?? "")
  }

  const handleSubmit = () => {
    if (testing || submitting || fatal || submitResult || !gateState.engagementOccurred) return
    submit(codeEditorRef.current?.getValue() ?? "")
  }

  const handleNextProblem = async () => {
    if (!student || !topicId) return
    try {
      const response = await fetch(
        `http://localhost:8000/students/${student.student_id}/topics/${topicId}/start`,
        { method: "POST" }
      )
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }
      const data = await response.json()
      if (!data.found) {
        console.error("No next problem available:", data.message)
        return
      }
      navigate(`/${topicId}/workspace/${data.attempt_id}`, { state: { problem: data } })
    } catch (error) {
      console.error("Error starting next problem:", error)
    }
  }

  const actionsDisabled = testing || submitting || fatal || !!submitResult

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

          <Button
            type="button"
            className="workspace__run-test"
            onClick={handleRunTest}
            disabled={actionsDisabled}
          >
            {testing ? "Running..." : "Run Test"}
          </Button>
          <Button
            type="button"
            className="workspace__submit"
            onClick={handleSubmit}
            disabled={actionsDisabled || !gateState.engagementOccurred}
          >
            {submitting ? "Submitting..." : "Submit"}
          </Button>
        </header>

        {submitResult && (
          <div
            className={`workspace__submit-banner ${
              submitResult.finalResult === "pass"
                ? "workspace__submit-banner--pass"
                : "workspace__submit-banner--fail"
            }`}
          >
            <span className="workspace__submit-banner-text">
              {submitResult.finalResult === "pass"
                ? "Passed! Nice work."
                : "Not quite — some tests didn't pass."}
            </span>
            {submitResult.nextProblem?.problem_id ? (
              <Button
                type="button"
                className="workspace__next-problem"
                onClick={handleNextProblem}
              >
                Next Problem
              </Button>
            ) : (
              <span className="workspace__submit-banner-text">
                No more problems available at this tier right now.
              </span>
            )}
          </div>
        )}

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
                <CodeEditor
                  ref={codeEditorRef}
                  defaultValue={problem?.starter_code ?? ""}
                  onChange={reportCodeChange}
                />
              </div>
              <TestOutput testCases={problem?.test_cases} testing={testing} testResult={testResult} />
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
