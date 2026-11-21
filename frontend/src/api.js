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

export async function uploadMediaFile(file, { title = '' } = {}) {
  return uploadFile('/api/upload-media', file, { title })
}

export async function uploadSubtitleFile(file, { encoding = 'utf-8-sig' } = {}) {
  return uploadFile('/api/toolbox/upload-subtitle', file, { encoding })
}

export async function uploadVideoFile(file, { title = '' } = {}) {
  return uploadFile('/api/upload-video', file, { title })
}

async function uploadFile(path, file, { title = '', encoding = '' } = {}) {
  const form = new FormData()
  form.append('file', file)
  if (title) form.append('title', title)
  if (encoding) form.append('encoding', encoding)
  const response = await fetch(path, {
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
