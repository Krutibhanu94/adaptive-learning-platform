//create a header with the text "problem"
//and below it create a div with the text "problem description" this component basically populate the problem description and the problem name from workspace

import "./problem.css"

function Problem({ problemName, problemDescription }) {
  return (
    <div className="problem">
      <div className="problem__bar">
        <span className="problem__header">Problem</span>
      </div>

      <div className="problem__content">
        <h3 className="problem__name">{problemName}</h3>
        <div className="problem__description">{problemDescription}</div>
      </div>
    </div>
  )
}

export default Problem
