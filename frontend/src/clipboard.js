export async function copyText(text, env = {}) {
  const value = String(text || "")
  if (!value) return false
  const nav = env.navigator ?? globalThis.navigator
  const doc = env.document ?? globalThis.document

  if (nav?.clipboard?.writeText) {
    try {
      await nav.clipboard.writeText(value)
      return true
    } catch {
      // LAN HTTP pages often fail Clipboard API permission checks; use textarea fallback below.
    }
  }

  if (!doc?.createElement || !doc?.body?.appendChild || !doc?.execCommand) {
    return false
  }

  const textarea = doc.createElement("textarea")
  textarea.value = value
  textarea.setAttribute?.("readonly", "")
  Object.assign(textarea.style || {}, {
    position: "fixed",
    top: "-1000px",
    left: "-1000px",
    opacity: "0",
  })
  doc.body.appendChild(textarea)
  textarea.select?.()
  let copied = false
  try {
    copied = Boolean(doc.execCommand("copy"))
  } finally {
    doc.body.removeChild(textarea)
  }
  return copied
}
