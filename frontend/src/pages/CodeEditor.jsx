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
    // Monaco's own defaultValue only ever seeds the editor at mount -- setting a new
    // defaultValue prop later (e.g. Workspace staying mounted across a Next Problem
    // navigation) is a no-op. This is how a caller actually replaces the editor's
    // content afterward.
    setValue: (newValue) => editorRef.current?.setValue(newValue ?? ""),
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
