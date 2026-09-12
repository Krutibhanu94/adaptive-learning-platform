import { forwardRef, useImperativeHandle, useRef } from "react"
import Editor from "@monaco-editor/react"

import "./CodeEditor.css"

const CodeEditor = forwardRef(function CodeEditor(
  { value, defaultValue = "", onChange, language = "python" },
  ref
) {
  const editorRef = useRef(null)

  useImperativeHandle(ref, () => ({
    getValue: () => editorRef.current?.getValue() ?? "",
  }))

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
          onMount={(editor) => {
            editorRef.current = editor
          }}
        />
      </div>
    </div>
  )
})

export default CodeEditor
