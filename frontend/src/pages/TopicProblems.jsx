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
      </div>

      <Separator className="topic-problems__divider" />

      <ItemGroup className="topic-problems__list">
        {problems.map((problem, index) => {
          const status = STATUS_ICON[problem.submit_result] ?? STATUS_ICON.no_submission

          return (
            <Fragment key={problem.problem_id}>
              <Item variant="default" className="topic-problems__item">
                <ItemMedia variant="icon">
                  <status.Icon className={status.className} />
                </ItemMedia>
                <ItemContent>
                  <ItemTitle>{problem.problem_name}</ItemTitle>
                </ItemContent>
                <ItemActions>
                  <ChevronRight className="topic-problems__item-arrow" />
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
