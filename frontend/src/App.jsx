import { AppBar } from "@/components/appBar"
import Dashboard from "@/pages/Dashboard"
import { useStudent } from "@/context/useStudent"
import './App.css'

function App() {
  const student = useStudent()

  return (
    <>
      <AppBar userName={student?.student_name} />
      <section id="center">
        <Dashboard />
      </section>
    </>
  )
}

export default App
