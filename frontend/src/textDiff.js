/** 按行 diff（LCS），用于章节正文变更预览。 */

function splitLines(text) {
  return (text || '').replace(/\r\n/g, '\n').split('\n')
}

function lcsTable(a, b) {
  const m = a.length
  const n = b.length
  const dp = Array.from({ length: m + 1 }, () => Array(n + 1).fill(0))
  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      if (a[i - 1] === b[j - 1]) dp[i][j] = dp[i - 1][j - 1] + 1
      else dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1])
    }
  }
  return dp
}

/** @returns {{ type: 'equal'|'add'|'remove', line: string }[]} */
export function diffLines(oldText, newText) {
  const a = splitLines(oldText)
  const b = splitLines(newText)
  const dp = lcsTable(a, b)
  const ops = []
  let i = a.length
  let j = b.length
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && a[i - 1] === b[j - 1]) {
      ops.push({ type: 'equal', line: a[i - 1] })
      i -= 1
      j -= 1
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      ops.push({ type: 'add', line: b[j - 1] })
      j -= 1
    } else {
      ops.push({ type: 'remove', line: a[i - 1] })
      i -= 1
    }
  }
  ops.reverse()
  return ops
}

export function diffStats(parts) {
  let added = 0
  let removed = 0
  let equal = 0
  for (const p of parts) {
    if (p.type === 'add') added += 1
    else if (p.type === 'remove') removed += 1
    else equal += 1
  }
  return { added, removed, equal }
}

export function hasDiff(oldText, newText) {
  return (oldText || '') !== (newText || '')
}
