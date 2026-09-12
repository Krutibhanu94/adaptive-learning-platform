import "./TestOutput.css"

function TestFailure({ failure }) {
  if (!failure) {
    return <div className="test-output__status test-output__status--fail">Tests failed.</div>
  }

  return (
    <div className="test-output__failure">
      <div className="test-output__status test-output__status--fail">Failed</div>
      {failure.assertion && (
        <div className="test-output__failure-row">
          <span className="test-output__example-key">Case:</span>
          <code className="test-output__example-value">{failure.assertion}</code>
        </div>
      )}
      {failure.actual != null && (
        <div className="test-output__failure-row">
          <span className="test-output__example-key">Your output:</span>
          <code className="test-output__example-value">{failure.actual}</code>
        </div>
      )}
      {failure.error && (
        <div className="test-output__failure-row">
          <span className="test-output__example-key">Error:</span>
          <code className="test-output__example-value">{failure.error}</code>
        </div>
      )}
    </div>
  )
}

// testCases holds every case the dataset provides (sometimes dozens) -- only shown
// before any Run Test click, so just the first few as LeetCode-style examples. After a
// click, testResult replaces this entirely: pass, or the one case that failed with rich
// detail (the checker only ever reports the first failure, not a per-case breakdown --
// check(candidate)'s asserts halt at the first one, by design).
function TestOutput({ testCases, testing, testResult }) {
  const exampleCases = (testCases ?? []).slice(0, 3)

  return (
    <div className="test-output">
      <div className="test-output__bar">
        <span className="test-output__header">Test Cases</span>
      </div>

      <div className="test-output__body">
        {testing && (
          <div className="test-output__status test-output__status--pending">Running tests...</div>
        )}

        {!testing && testResult && (
          testResult.all_passed ? (
            <div className="test-output__status test-output__status--pass">All tests passed</div>
          ) : (
            <TestFailure failure={testResult.failures?.[0]} />
          )
        )}

        {!testing && !testResult && (
          <div className="test-output__examples">
            {exampleCases.length === 0 && (
              <div className="test-output__empty">No example cases available for this problem.</div>
            )}
            {exampleCases.map((example, index) => (
              <div key={index} className="test-output__example">
                <div className="test-output__example-label">Example {index + 1}</div>
                <div className="test-output__example-row">
                  <span className="test-output__example-key">Input:</span>
                  <code className="test-output__example-value">{example.input}</code>
                </div>
                <div className="test-output__example-row">
                  <span className="test-output__example-key">Output:</span>
                  <code className="test-output__example-value">{example.output}</code>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default TestOutput
