export async function api(path, payload = {}) {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  const data = await response.json()
  if (!response.ok) {
    throw new Error(data.error || 'request failed')
  }
  return data
}

export async function getJson(path) {
  const response = await fetch(path)
  const data = await response.json()
  if (!response.ok) {
    throw new Error(data.error || 'request failed')
  }
  return data
}
