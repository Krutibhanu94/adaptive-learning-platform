import { BrowserRouter, Routes, Route } from "react-router-dom"
import { AppBar } from "@/components/appBar"
import Dashboard from "@/pages/Dashboard"
import Topics from "@/pages/Topics"
import TopicProblems from "@/pages/TopicProblems"
import { useStudent } from "@/context/useStudent"
import './App.css'

function App() {
  const student = useStudent()

  return (
    <BrowserRouter>
      <AppBar userName={student?.student_name} />
      <section id="center">
        <Routes>
          <Route path="/" element={<Dashboard />}>
            <Route index element={<Topics />} />
            <Route path=":topicId" element={<TopicProblems />} />
          </Route>
        </Routes>
      </section>
    </BrowserRouter>
  )
}

export default App
