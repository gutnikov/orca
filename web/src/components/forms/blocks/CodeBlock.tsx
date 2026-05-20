import { Highlight, themes, type Language } from "prism-react-renderer"

export default function CodeBlock({ content, language }: { content: string; language?: string }) {
  const lang = (language ?? "tsx") as Language
  return (
    <Highlight code={content.trim()} language={lang} theme={themes.nightOwl}>
      {({ className, style, tokens, getLineProps, getTokenProps }) => (
        <pre
          className={`${className} rounded-lg p-4 overflow-x-auto text-xs leading-relaxed font-mono`}
          style={style}
        >
          {tokens.map((line, i) => (
            <div key={i} {...getLineProps({ line })}>
              {line.map((token, k) => (
                <span key={k} {...getTokenProps({ token })} />
              ))}
            </div>
          ))}
        </pre>
      )}
    </Highlight>
  )
}
