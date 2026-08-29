import { useContext } from "react"

import { StudentContext } from "@/context/StudentContext"

function useStudent() {
  return useContext(StudentContext)
}

export { useStudent }
