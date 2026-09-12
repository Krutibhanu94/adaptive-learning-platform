import { Fragment, useState, useEffect } from 'react'
import { useParams, useNavigate } from "react-router-dom"
import { ArrowLeft, CheckCircle2, Circle, CircleDashed, ChevronRight, XCircle } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Item, ItemGroup, ItemMedia, ItemContent, ItemTitle, ItemActions, ItemSeparator } from "@/components/ui/item"
import { Separator } from "@/components/ui/separator"
import { useStudent } from "@/context/useStudent"

import "./TopicProblems.css"

const STATUS_ICON = {
  pass: { Icon: CheckCircle2, className: "text-green-600" },
  fail: { Icon: XCircle, className: "text-red-600" },
  partial: { Icon: CircleDashed, className: "text-amber-500" },
  no_submission: { Icon: Circle, className: "text-muted-foreground" },
}

function TopicProblems() {
  const { topicId } = useParams()
  const navigate = useNavigate()
  const student = useStudent()

  const [problems, setProblems] = useState([])
  const [starting, setStarting] = useState(false)

  const handleStart = async () => {
    if (!student || starting) return
    setStarting(true)

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
        console.error("No problem available to start:", data.message)
        return
      }

      navigate(`/${topicId}/workspace/${data.attempt_id}`, { state: { problem: data } })
    } catch (error) {
      console.error("Error starting attempt:", error)
    } finally {
      setStarting(false)
    }
  }

  useEffect(() => {
    if (!student) return

    const fetchProgress = async () => {
      try {
        const response = await fetch(
          `http://localhost:8000/student/${student.student_id}/topics/${topicId}/progress`
        )

        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`)
        }

        const data = await response.json()
        setProblems(data.progress)
      } catch (error) {
        console.error("Error fetching topic progress:", error)
      }
    }

    fetchProgress()
  }, [student, topicId])

  return (
    <div className="topic-problems">
      <div className="topic-problems__heading-row">
        <Button
          type="button"
          aria-label="Back to topics"
          className="topic-problems__back"
          onClick={() => navigate(-1)}
        >
          <ArrowLeft className="topic-problems__back-icon" />
        </Button>

        <h1 className="topic-problems__heading">Problems</h1>

        <Button
          type="button"
          className="topic-problems__start"
          onClick={handleStart}
          disabled={starting}
        >
          {starting ? "Starting..." : "Start Problem"}
        </Button>
      </div>

      <Separator className="topic-problems__divider" />

      <ItemGroup className="topic-problems__list">
        {problems.map((problem, index) => {
          const status = STATUS_ICON[problem.submit_result] ?? STATUS_ICON.no_submission
          // Only the problem with a currently open (not-yet-submitted) attempt is
          // resumable directly from this list -- anything else needs a fresh attempt via
          // Start Problem instead.
          const isResumable = problem.submit_result === "no_submission" && problem.attempt_id

          return (
            <Fragment key={problem.problem_id}>
              <Item
                variant="default"
                className={`topic-problems__item ${isResumable ? "topic-problems__item--resumable" : ""}`}
                onClick={isResumable ? () => navigate(`/${topicId}/workspace/${problem.attempt_id}`) : undefined}
              >
                <ItemMedia variant="icon">
                  <status.Icon className={status.className} />
                </ItemMedia>
                <ItemContent>
                  <ItemTitle>{problem.problem_name}</ItemTitle>
                </ItemContent>
                <ItemActions>
                  <ChevronRight
                    className={`topic-problems__item-arrow ${isResumable ? "topic-problems__item-arrow--active" : ""}`}
                  />
                </ItemActions>
              </Item>

              {index < problems.length - 1 && <ItemSeparator />}
            </Fragment>
          )
        })}
      </ItemGroup>
    </div>
  )
}

export default TopicProblems
