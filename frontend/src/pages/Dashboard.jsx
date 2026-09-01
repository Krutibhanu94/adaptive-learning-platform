import { useEffect, useState } from "react"
import { Link, Outlet, useParams } from "react-router-dom"

import {
  Breadcrumb,
  BreadcrumbList,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"
import { Separator } from "@/components/ui/separator"

import "./Dashboard.css"

function Dashboard() {
  const [topics, setTopics] = useState([])
  const { topicId } = useParams()

  useEffect(() => {
    const fetchTopics = async () => {
      try {
        const response = await fetch("http://localhost:8000/topics")

        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`)
        }

        const data = await response.json()
        setTopics(data.topics)
      } catch (error) {
        console.error("Error fetching topics:", error)
      }
    }

    fetchTopics()
  }, [])

  const currentTopic = topicId
    ? topics.find((topic) => String(topic.topic_id) === topicId)
    : null

  return (
    <div className="dashboard">
      <h1 className="dashboard__heading">Student Dashboard</h1>

      <Breadcrumb className="dashboard__breadcrumb">
        <BreadcrumbList>
          <BreadcrumbItem>
            <BreadcrumbLink asChild>
              <Link to="/">Dashboard</Link>
            </BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          {currentTopic ? (
            <>
              <BreadcrumbItem>
                <BreadcrumbLink asChild>
                  <Link to="/">Topics</Link>
                </BreadcrumbLink>
              </BreadcrumbItem>
              <BreadcrumbSeparator />
              <BreadcrumbItem>
                <BreadcrumbPage>{currentTopic.topic_name}</BreadcrumbPage>
              </BreadcrumbItem>
            </>
          ) : (
            <BreadcrumbItem>
              <BreadcrumbPage>Topics</BreadcrumbPage>
            </BreadcrumbItem>
          )}
        </BreadcrumbList>
      </Breadcrumb>

      <Separator className="dashboard__divider" />

      <Outlet context={{ topics }} />
    </div>
  )
}

export default Dashboard
