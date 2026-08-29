import { createContext, useEffect, useState } from "react"

const STUDENT_ID = 1

const StudentContext = createContext(null)

function StudentProvider({ children }) {
  const [student, setStudent] = useState(null)

  useEffect(() => {
    const fetchStudent = async () => {
      try {
        const response = await fetch(`http://localhost:8000/students/${STUDENT_ID}`)

        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`)
        }

        const data = await response.json()

        if (data.found) {
          setStudent(data.student)
        }
      } catch (error) {
        console.error("Error fetching student:", error)
      }
    }

    fetchStudent()
  }, [])

  return (
    <StudentContext.Provider value={student}>
      {children}
    </StudentContext.Provider>
  )
}

export { StudentContext, StudentProvider }
