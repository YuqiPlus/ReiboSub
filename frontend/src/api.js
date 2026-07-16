export async function api(path, payload = {}) {
  return requestJson(path, 'POST', payload)
}

export async function deleteJson(path, payload = {}) {
  return requestJson(path, 'DELETE', payload)
}

export async function patchJson(path, payload = {}) {
  return requestJson(path, 'PATCH', payload)
}

async function requestJson(path, method, payload) {
  const response = await fetch(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload ?? {}),
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

export async function uploadVideoFile(file, { title = '' } = {}) {
  const form = new FormData()
  form.append('file', file)
  if (title) form.append('title', title)
  const response = await fetch('/api/upload-video', {
    method: 'POST',
    body: form,
  })
  const data = await response.json()
  if (!response.ok) {
    throw new Error(data.error || 'request failed')
  }
  return data
}

export async function uploadProjectCover(file, { projectPath }) {
  const form = new FormData()
  form.append('file', file)
  form.append('project_path', projectPath)
  const response = await fetch('/api/upload-project-cover', {
    method: 'POST',
    body: form,
  })
  const data = await response.json()
  if (!response.ok) {
    throw new Error(data.error || 'request failed')
  }
  return data
}
