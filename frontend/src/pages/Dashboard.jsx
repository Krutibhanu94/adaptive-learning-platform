import { useEffect, useState } from "react"

import Topics from "@/pages/Topics"
import {
  Breadcrumb,
  BreadcrumbList,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from "@/components/ui/breadcrumb"

import "./Dashboard.css"

function Dashboard() {
  const [topics, setTopics] = useState([])

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

  return (
    <div className="dashboard">
      <h1 className="dashboard__heading">Student Dashboard</h1>

      <Breadcrumb className="dashboard__breadcrumb">
        <BreadcrumbList>
          <BreadcrumbItem>
            <BreadcrumbLink href="#">Dashboard</BreadcrumbLink>
          </BreadcrumbItem>
          <BreadcrumbSeparator />
          <BreadcrumbItem>
            <BreadcrumbPage>Topics</BreadcrumbPage>
          </BreadcrumbItem>
        </BreadcrumbList>
      </Breadcrumb>

      <hr className="dashboard__divider" />

      <Topics topics={topics} />
    </div>
  )
}

export default Dashboard
