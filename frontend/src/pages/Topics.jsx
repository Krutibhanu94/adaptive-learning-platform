import { useNavigate, useOutletContext } from "react-router-dom"

import { Button } from "@/components/ui/button"
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardFooter,
} from "@/components/ui/card"

import "./Topics.css"

function Topics() {
  const { topics } = useOutletContext()
  const navigate = useNavigate()

  return (
    <div className="topic-cards">
      {topics.map((topic) => (
        <Card key={topic.topic_id} className="topic-card">
          <CardHeader>
            <CardTitle className="topic-card__title">{topic.topic_name}</CardTitle>
            <hr className="topic-card__divider" />
            <CardDescription className="topic-card__description">
              {topic.topic_description}
            </CardDescription>
          </CardHeader>
          <CardFooter className="topic-card__footer">
            <Button
              className="topic-card__button"
              onClick={() => navigate(`/${topic.topic_id}`)}
            >
              Access Topic
            </Button>
          </CardFooter>
        </Card>
      ))}
    </div>
  )
}

export default Topics
