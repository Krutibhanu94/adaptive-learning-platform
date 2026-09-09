//lets use the code editor from the react monaco editor package and make the editor
//my editor defaults to python

import Editor from "@monaco-editor/react"

import "./CodeEditor.css"

function CodeEditor({ value, defaultValue = "", onChange, language = "python" }) {
  return (
    <div className="code-editor">
      <div className="code-editor__language">
        <span className="code-editor__language-badge">{language}</span>
      </div>

      <div className="code-editor__pane">
        <Editor
          height="100%"
          theme="vs-dark"
          defaultLanguage={language}
          defaultValue={defaultValue}
          value={value}
          onChange={onChange}
        />
      </div>
    </div>
  )
}

export default CodeEditor
