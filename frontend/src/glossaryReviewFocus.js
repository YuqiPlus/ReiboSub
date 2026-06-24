export function nextPendingReviewIndex(items, currentIndex) {
  const laterIndex = items.findIndex((item, index) => index > currentIndex && !item.reviewed)
  if (laterIndex !== -1) return laterIndex
  return items.findIndex((item, index) => index !== currentIndex && !item.reviewed)
}

export function shouldConfirmReviewEnter(event, composing = false) {
  if (composing) return false
  if (event?.isComposing) return false
  if (event?.keyCode === 229) return false
  return true
}
